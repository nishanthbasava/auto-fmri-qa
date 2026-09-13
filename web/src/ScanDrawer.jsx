import { useEffect, useState } from "react";
import { api, can, fetchImage } from "./api.js";

const FIGS = [
  ["carpet", "Confounds & carpet plot"],
  ["coreg", "BOLD → T1w registration"],
  ["t1norm", "T1w → MNI152NLin2009cAsym"],
];

const fmt = (v, d = 3) => (v == null ? "—" : Number(v).toFixed(d));

export default function ScanDrawer({ user, runId, scan, onClose, onDecided }) {
  const [urls, setUrls] = useState({});
  const [note, setNote] = useState("");
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const canDecide = can(user, "reviewer");
  const scanPath = `/api/runs/${runId}/scans/${encodeURIComponent(scan.key)}`;

  useEffect(() => {
    let alive = true;
    const made = [];
    FIGS.forEach(([kind]) => {
      const name = scan.figures?.[kind];
      if (!name) return;
      fetchImage(`/api/runs/${runId}/figures/${name}`)
        .then((u) => {
          made.push(u);
          if (alive) setUrls((prev) => ({ ...prev, [kind]: u }));
        })
        .catch(() => {});
    });
    return () => {
      alive = false;
      made.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [runId, scan]);

  useEffect(() => {
    api(`${scanPath}/history`).then((d) => setHistory(d.history)).catch(() => setHistory([]));
  }, [scanPath, scan.decision]);

  const decide = async (decision) => {
    setBusy(true);
    setErr("");
    try {
      // the reviewer's identity comes from the login token; nothing to type
      await api(`${scanPath}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, note }),
      });
      setNote("");
      onDecided();
    } catch (ex) {
      setErr(ex.message);
    } finally {
      setBusy(false);
    }
  };

  const m = scan;
  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <div className="drawer">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>
            {scan.sub} · {scan.ses}{" "}
            <span className={`chip ${scan.status}`}>{scan.status}</span>{" "}
            {scan.verify_flags.length > 0 && <span className="chip VERIFY">VERIFY</span>}
          </h2>
          <button className="ghost" onClick={onClose}>✕ close</button>
        </div>

        <div className="kv">
          <span>Mean FD</span><b>{fmt(m.mean_fd)} mm</b>
          <span>Max FD</span><b>{fmt(m.max_fd, 2)} mm</b>
          <span>Outliers</span><b>{fmt(m.outlier_percent, 1)}%</b>
          <span>Retained</span><b>{fmt(m.retained_minutes, 1)} min</b>
          <span>TR / volumes</span><b>{fmt(m.tr, 2)} s · {m.n_volumes ?? "—"}</b>
          {m.vendor && <><span>Scanner</span><b>{m.vendor}</b></>}
        </div>

        {scan.reasons.length > 0 && (
          <p className="pill">Pipeline reasons: {scan.reasons.join("; ")}</p>
        )}
        {scan.verify_flags.length > 0 && (
          <p className="pill" style={{ color: "var(--verify)" }}>
            Verify: {scan.verify_flags.join("; ")}
          </p>
        )}
        {scan.review && (
          <p className="pill">
            Agent figure review — <b>{scan.review.rating}</b>
            {scan.review.panel && scan.review.panel !== "none" ? ` (${scan.review.panel})` : ""}
            {scan.review.note ? `: ${scan.review.note}` : ""}
            {scan.review.context?.length > 0 && (
              <span className="faint">
                {" "}· grounded in {scan.review.context.map((c) => c.section).join("; ")}
              </span>
            )}
          </p>
        )}
        {scan.missing.length > 0 && (
          <p className="err">Missing outputs: {scan.missing.join(", ")}</p>
        )}

        <div className="card" style={{ marginTop: 12 }}>
          <h2>Reviewer decision</h2>
          {scan.decision && (
            <p className="pill">
              Current: <b>{scan.decision.decision}</b> by {scan.decision.by || "?"} at{" "}
              {scan.decision.at}
              {scan.decision.note ? ` — “${scan.decision.note}”` : ""}
            </p>
          )}
          {canDecide ? (
            <div className="row">
              <input
                id="decision-note"
                placeholder="note (optional)"
                style={{ flex: 1, minWidth: 160 }}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <button className="keep" disabled={busy} onClick={() => decide("keep")}>Keep</button>
              <button className="drop" disabled={busy} onClick={() => decide("drop")}>Drop</button>
              {scan.decision && (
                <button disabled={busy} onClick={() => decide("clear")}>Clear</button>
              )}
              <span className="pill">recorded as {user.username}</span>
            </div>
          ) : (
            <p className="pill">Recording decisions needs the <b>reviewer</b> role (you are {user.role}).</p>
          )}
          {err && <p className="err">{err}</p>}
          {history.length > 0 && (
            <ul className="history">
              {history.map((h) => (
                <li key={h.id}>
                  <span className={`chip ${h.decision === "keep" ? "INCLUDE" : h.decision === "drop" ? "EXCLUDE" : "outline"}`}>
                    {h.decision}
                  </span>{" "}
                  {h.by} · {h.at}
                  {h.note ? ` — “${h.note}”` : ""}
                  <span className="faint"> (status then: {h.status_at_decision})</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {FIGS.map(([kind, label]) => (
          <div className="figure-box" key={kind}>
            <div className="cap">{label}</div>
            {urls[kind]
              ? <img src={urls[kind]} alt={label} />
              : <p className="pill" style={{ padding: 10 }}>
                  {scan.figures?.[kind] ? "Loading…" : "Not rendered (launch with “render figures”)."}
                </p>}
          </div>
        ))}
      </div>
    </>
  );
}
