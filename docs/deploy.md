# Deploying on the lab machine (Docker)

This doubles as the Docker walkthrough — each concept is introduced where this
repo actually uses it.

## The mental model

An **image** is a frozen filesystem + a start command, built once from a
`Dockerfile`. A **container** is a running (disposable) instance of an image.
Anything a container writes to its own filesystem dies with it — which is why
everything we care about (`runs/`, `staged/`, `.env`) lives *outside* the
containers and is attached at start time.

This platform is three containers:

| service | image contents | talks to |
|---|---|---|
| `db`    | Postgres 16: users, review decisions, audit log (named volume `pgdata`) | `api` only |
| `api`   | Python + Chromium + node, the pipeline, FastAPI on :8000 | `db`; not published |
| `web`   | nginx + the built React bundle on :80 | published as :8080, proxies `/api/*` to `api` |

`api` waits for `db`'s healthcheck (`pg_isready`), then its entrypoint runs
`autoqa db upgrade` (Alembic migrations, idempotent) before `autoqa serve`.

The browser only ever sees one origin (`http://lab-machine:8080`); nginx
forwards `/api/*` over Docker's private network to the api container. The api
container's port is never published to the host, so the password check in
FastAPI is the only door.

## Dockerfile.api, line by line idea

- `FROM python:3.11-slim` — start from a minimal Python filesystem.
- `COPY requirements.txt` + `pip install` **before** copying source: Docker
  caches each instruction as a layer, and a layer is rebuilt only when its
  inputs change. Requirements change rarely, source changes constantly — this
  ordering means a code edit rebuilds in seconds instead of re-downloading
  Chromium every time.
- `playwright install --with-deps chromium` — the figure renderer needs a real
  browser; `--with-deps` also installs its system libraries.
- `npm install pptxgenjs` in `/app` — deck builds shell out to node, and node
  resolves packages by walking up from the script to the nearest
  `node_modules`.
- `COPY autoqa/` + `pip install --no-deps .` last — the cheap, frequently-changing
  layer. `--no-deps` because every dependency already came from the cached
  requirements layer; this step only registers the package and the `autoqa`
  console script.
- `CMD autoqa serve` — what runs when the container starts. The
  pipeline itself needs no separate service: the API launches it as
  subprocesses (`python -m autoqa.cli run ...`) inside this same container.

## Dockerfile.web: multi-stage build

Stage 1 (`node:20-slim`) runs `npm install && npm run build` to produce the
static bundle. Stage 2 (`nginx:alpine`) copies **only** `dist/` out of stage 1.
The shipped image contains nginx and ~200 KB of files — no node, no sources.

## docker-compose.yml

Compose is "run these N containers together on a private network, with these
volumes and env": service names become hostnames (nginx reaches the API at
`http://api:8000`), `volumes:` bind host folders into containers
(`./runs:/app/runs` — results survive rebuilds), and `env_file: .env` injects
secrets at runtime so they are never baked into an image. `.dockerignore`
additionally keeps `.env`, `runs/` and `staged/` out of the build context
entirely.

## Runbook

```bash
# 0) one-time: install Docker Desktop (mac) or docker engine + compose (linux)

# 1) secrets -- copy .env.example to .env (gitignored AND dockerignored) and fill in
#      JWT_SECRET=$(openssl rand -hex 32)         # else tokens die on every API restart
#      POSTGRES_PASSWORD=$(openssl rand -hex 16)  # else the dev default is used
#      ANTHROPIC_API_KEY=...                      # only needed to run LLM reviews
#      APP_PASSWORD=...                           # optional bootstrap admin (cannot record decisions)

# 2) data -- put a staged fMRIPrep subset in staged/ (from the cluster):
#      autoqa stage /path/to/derivatives -o staged/batch1 --task rest

# 3) build + start (first build ~5-10 min, mostly the Chromium layer):
docker compose up -d --build

# 4) create the first admin, then reviewers:
docker compose exec api autoqa users add <you> --role admin
docker compose exec api autoqa users add <colleague> --role reviewer

# 5) open http://<lab-machine-ip>:8080 from any machine on the lab network,
#    log in, launch a run. Roles: viewer (read), reviewer (keep/drop decisions),
#    admin (launch runs, build decks, audit log at /api/audit, manage users).

# observe / operate:
docker compose ps                 # status + health
docker compose logs -f api        # live API + pipeline logs
docker compose restart api
docker compose down               # stop (runs/ and staged/ are untouched)
```

After editing code: `docker compose up -d --build` again — only the changed
layers rebuild.

## Data model

- `runs/<run>/state.json` is the pipeline's journal: metrics, labels, rendered
  figures, LLM review. The API reads it; it never writes decisions into it.
- Postgres holds what people do: `users`, `decisions` (append-only -- a
  "clear" is a new row, the current decision is the latest row) and
  `audit_events` (login, launch, decision, deck build; actor, target, IP,
  before/after). On Postgres the migration revokes UPDATE/DELETE on both
  append-only tables from the app role.
- `autoqa db sync-journal runs/<run>` copies the latest decisions into the
  journal for the deck builder and `autoqa audit surface`.
- Background jobs (pipeline, review, deck) are rows in a `jobs` table, so
  status survives an API restart; a job orphaned by a restart is reported as
  `interrupted` rather than lost.
- `GET /api/metrics` (Prometheus text) and `/api/metrics.json` report p50/p95/p99
  latency per route from a per-route reservoir of real samples.

## ADNI DUA boundary

Keep this on the lab network only: bind on a machine that is not
internet-reachable, never port-forward 8080, and leave the api service
unpublished (it already is). Per-user login gates every endpoint and every mutation is audited — but
network isolation is the real control; auth is defense in depth.
