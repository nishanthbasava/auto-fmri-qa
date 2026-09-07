import { useEffect, useState } from "react";
import { api, fetchImage } from "./api.js";

const FIGS = [
  ["carpet", "Confounds & carpet plot"],
  ["coreg", "BOLD → T1w registration"],
  ["t1norm", "T1w → MNI152NLin2009cAsym"],
];

const fmt = (v, d = 3) => (v == null ? "—" : Number(v).toFixed(d));

export default function ScanDrawer({ runId, scan, onClose, onDecided }) {
  const [urls, setUrls] = useState({});
  const [by, setBy] = useState(localStorage.getItem("afq_reviewer") || "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

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

  const decide = async (decision) => {
    setBusy(true);
    setErr("");
    localStorage.setItem("afq_reviewer", by);
    try {
      await api(`/api/runs/${runId}/scans/${encodeURIComponent(scan.key)}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, by, note }),
      });
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
            {scan.review.panel ? ` (${scan.review.panel})` : ""}
            {scan.review.note ? `: ${scan.review.note}` : ""}
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
          <div className="row">
            <input
              placeholder="your initials"
              style={{ width: 110 }}
              value={by}
              onChange={(e) => setBy(e.target.value)}
            />
            <input
              placeholder="note (optional)"
              style={{ flex: 1, minWidth: 160 }}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <button className="keep" disabled={busy || !by} onClick={() => decide("keep")}>Keep</button>
            <button className="drop" disabled={busy || !by} onClick={() => decide("drop")}>Drop</button>
            {scan.decision && (
              <button disabled={busy} onClick={() => decide("clear")}>Clear</button>
            )}
          </div>
          {!by && <p className="pill" style={{ marginTop: 6 }}>Enter initials to record a decision (audit trail).</p>}
          {err && <p className="err">{err}</p>}
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
