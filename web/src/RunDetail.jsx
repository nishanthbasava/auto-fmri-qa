import { useEffect, useMemo, useState } from "react";
import { api, getToken } from "./api.js";
import ScanDrawer from "./ScanDrawer.jsx";

const ACTIVE = ["starting", "pipeline", "review", "deck"];
const COLS = [
  ["sub", "Subject", false],
  ["ses", "Session", false],
  ["status", "Status", false],
  ["mean_fd", "Mean FD", true],
  ["max_fd", "Max FD", true],
  ["outlier_percent", "Outliers %", true],
  ["retained_minutes", "Retained min", true],
  ["tr", "TR s", true],
];
const fmt = (v, d = 3) => (v == null ? "—" : Number(v).toFixed(d));

export default function RunDetail({ runId, onBack }) {
  const [info, setInfo] = useState(null);
  const [scans, setScans] = useState([]);
  const [sort, setSort] = useState({ col: "sub", dir: 1 });
  const [statusF, setStatusF] = useState("ALL");
  const [verifyOnly, setVerifyOnly] = useState(false);
  const [undecidedOnly, setUndecidedOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(null); // scan key
  const [log, setLog] = useState(null);
  const [err, setErr] = useState("");

  const load = () => {
    api(`/api/runs/${runId}`).then(setInfo).catch((e) => setErr(e.message));
    api(`/api/runs/${runId}/scans`).then((d) => setScans(d.scans)).catch(() => {});
  };
  useEffect(load, [runId]);

  const running = info && ACTIVE.includes(info.job.phase);
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [running, runId]);

  useEffect(() => {
    if (log == null) return undefined;
    const pull = () => api(`/api/runs/${runId}/log`).then((d) => setLog(d.log)).catch(() => {});
    pull();
    if (!running) return undefined;
    const t = setInterval(pull, 4000);
    return () => clearInterval(t);
  }, [log != null, running, runId]);

  const shown = useMemo(() => {
    let rows = scans;
    if (statusF !== "ALL") rows = rows.filter((s) => s.status === statusF);
    if (verifyOnly) rows = rows.filter((s) => s.verify_flags.length);
    if (undecidedOnly) rows = rows.filter((s) => !s.decision);
    if (search) rows = rows.filter((s) => s.sub.toLowerCase().includes(search.toLowerCase()));
    const { col, dir } = sort;
    return [...rows].sort((a, b) => {
      const x = a[col], y = b[col];
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  }, [scans, statusF, verifyOnly, undecidedOnly, search, sort]);

  const clickSort = (col) =>
    setSort((s) => ({ col, dir: s.col === col ? -s.dir : 1 }));

  const buildDeck = async () => {
    try {
      await api(`/api/runs/${runId}/deck`, { method: "POST" });
      load();
      setLog("");
    } catch (ex) { setErr(ex.message); }
  };

  const downloadDeck = async () => {
    const res = await fetch(`/api/runs/${runId}/deck`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) { setErr("deck not built yet"); return; }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${runId}_review_deck.pptx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const openScan = scans.find((s) => s.key === open);

  return (
    <div className="page">
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <button className="ghost" onClick={onBack}>← runs</button>
            <h2 style={{ margin: 0 }}>{runId}</h2>
            {info && (
              <span className={info.job.phase === "failed" ? "err" : "pill"}>
                {running && <span className="spin" style={{ marginRight: 6 }} />}
                {info.job.phase}
              </span>
            )}
          </div>
          <div className="row">
            <button onClick={() => setLog(log == null ? "" : null)}>
              {log == null ? "Show log" : "Hide log"}
            </button>
            <button onClick={buildDeck} disabled={running}>Build deck</button>
            <button className="primary" onClick={downloadDeck} disabled={!info?.has_deck}>
              Download deck
            </button>
          </div>
        </div>
        {info && (
          <div style={{ marginTop: 14 }}>
            <span className="stat"><b>{info.n_scans}</b><span>scans</span></span>
            <span className="stat"><b style={{ color: "var(--include)" }}>{info.counts.INCLUDE || 0}</b><span>include</span></span>
            <span className="stat"><b style={{ color: "var(--caution)" }}>{info.counts.CAUTION || 0}</b><span>caution</span></span>
            <span className="stat"><b style={{ color: "var(--exclude)" }}>{info.counts.EXCLUDE || 0}</b><span>exclude</span></span>
            <span className="stat"><b style={{ color: "var(--verify)" }}>{info.n_verify}</b><span>verify</span></span>
            <span className="stat"><b>{info.n_decided}</b><span>decided</span></span>
          </div>
        )}
        {info?.criteria && (
          <p className="pill" style={{ marginTop: 4 }}>
            Criteria: mean FD &gt; {info.criteria.exclusion?.mean_fd_mm} mm excludes ·{" "}
            outliers &gt; {info.criteria.caution?.motion_outlier_percent}% cautions ·{" "}
            outlier mode “{info.criteria.outlier_definition?.mode}”
          </p>
        )}
        {err && <p className="err">{err}</p>}
        {log != null && <pre className="log">{log || "…"}</pre>}
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <select value={statusF} onChange={(e) => setStatusF(e.target.value)}>
            {["ALL", "INCLUDE", "CAUTION", "EXCLUDE"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <label className="check">
            <input type="checkbox" checked={verifyOnly} onChange={(e) => setVerifyOnly(e.target.checked)} />
            VERIFY only
          </label>
          <label className="check">
            <input type="checkbox" checked={undecidedOnly} onChange={(e) => setUndecidedOnly(e.target.checked)} />
            undecided only
          </label>
          <input placeholder="filter subject…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <span className="pill">{shown.length} of {scans.length} scans</span>
        </div>
        <table>
          <thead>
            <tr>
              {COLS.map(([col, label, num]) => (
                <th
                  key={col}
                  className={(num ? "num " : "") + (sort.col === col ? "sorted" : "")}
                  onClick={() => clickSort(col)}
                >
                  {label}{sort.col === col ? (sort.dir > 0 ? " ↑" : " ↓") : ""}
                </th>
              ))}
              <th>Flags</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr key={s.key} onClick={() => setOpen(s.key)}>
                <td><b>{s.sub}</b></td>
                <td>{s.ses}</td>
                <td><span className={`chip ${s.status}`}>{s.status}</span></td>
                <td className="num">{fmt(s.mean_fd)}</td>
                <td className="num">{fmt(s.max_fd, 2)}</td>
                <td className="num">{fmt(s.outlier_percent, 1)}</td>
                <td className="num">{fmt(s.retained_minutes, 1)}</td>
                <td className="num">{fmt(s.tr, 2)}</td>
                <td>
                  {s.verify_flags.length > 0 && <span className="chip VERIFY">VERIFY</span>}{" "}
                  {s.review && <span className="chip outline">{s.review.rating}</span>}
                </td>
                <td>
                  {s.decision
                    ? <span className={`chip ${s.decision.decision === "keep" ? "INCLUDE" : "EXCLUDE"}`}>
                        {s.decision.decision}
                      </span>
                    : <span className="pill">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openScan && (
        <ScanDrawer
          runId={runId}
          scan={openScan}
          onClose={() => setOpen(null)}
          onDecided={() => { load(); }}
        />
      )}
    </div>
  );
}
