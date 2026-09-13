"""Request timing + a Prometheus-style /api/metrics.

A pure ASGI middleware times every request, tags it with a request id, and
keeps a bounded reservoir of latencies per route so percentiles are computed
from real samples (not a running mean, which hides tail latency).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

log = logging.getLogger("autoqa.api")

RESERVOIR = 2000


class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.latency = defaultdict(lambda: deque(maxlen=RESERVOIR))   # route -> ms samples
        self.count = defaultdict(int)                                  # (route, status) -> n
        self.started = time.time()

    def add(self, route: str, status: int, ms: float) -> None:
        with self._lock:
            self.latency[route].append(ms)
            self.count[(route, status)] += 1

    @staticmethod
    def _q(samples, q):
        if not samples:
            return None
        s = sorted(samples)
        return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]

    def snapshot(self) -> dict:
        with self._lock:
            routes = {}
            for route, samples in self.latency.items():
                routes[route] = {"n": len(samples),
                                 "p50_ms": self._q(samples, 0.50),
                                 "p95_ms": self._q(samples, 0.95),
                                 "p99_ms": self._q(samples, 0.99)}
            counts = {f"{r} {s}": n for (r, s), n in self.count.items()}
        return {"uptime_s": round(time.time() - self.started, 1), "routes": routes, "counts": counts}

    def prometheus(self) -> str:
        snap = self.snapshot()
        out = ["# HELP autoqa_request_latency_ms request latency by route (reservoir percentiles)",
               "# TYPE autoqa_request_latency_ms summary"]
        for route, r in sorted(snap["routes"].items()):
            for q in ("p50", "p95", "p99"):
                v = r[f"{q}_ms"]
                if v is not None:
                    out.append(f'autoqa_request_latency_ms{{route="{route}",quantile="{q}"}} {v:.2f}')
        out += ["# HELP autoqa_requests_total requests by route and status",
                "# TYPE autoqa_requests_total counter"]
        with self._lock:
            for (route, status), n in sorted(self.count.items()):
                out.append(f'autoqa_requests_total{{route="{route}",status="{status}"}} {n}')
        out.append(f"autoqa_uptime_seconds {snap['uptime_s']}")
        return "\n".join(out) + "\n"


STATS = Stats()


def route_template(scope) -> str:
    """'/api/runs/{run_id}/scans' rather than the concrete path, so one route = one series."""
    route = scope.get("route")
    path = getattr(route, "path", None) or scope.get("path", "?")
    return f"{scope.get('method', '?')} {path}"


class TimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            ms = (time.perf_counter() - t0) * 1000
            route = route_template(scope)
            STATS.add(route, status_holder["status"], ms)
            log.info(json.dumps({"rid": rid, "route": route, "status": status_holder["status"],
                                 "ms": round(ms, 2)}))
