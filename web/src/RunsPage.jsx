import { useEffect, useState } from "react";
import { api } from "./api.js";

const ACTIVE = ["starting", "pipeline", "review", "deck"];

export default function RunsPage({ onOpen }) {
  const [runs, setRuns] = useState(null);
  const [inputs, setInputs] = useState([]);
  const [form, setForm] = useState({ run_id: "", input: "", render: true, review: false });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    api("/api/runs").then((d) => setRuns(d.runs)).catch((e) => setErr(e.message));
  };

  useEffect(() => {
    load();
    api("/api/inputs")
      .then((d) => {
        setInputs(d.inputs);
        if (d.inputs.length) setForm((f) => ({ ...f, input: d.inputs[0].name }));
      })
      .catch(() => {});
  }, []);

  // poll while any job is active
  useEffect(() => {
    if (!runs || !runs.some((r) => ACTIVE.includes(r.job.phase))) return undefined;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [runs]);

  const launch = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api("/api/runs", { method: "POST", body: JSON.stringify(form) });
      setForm((f) => ({ ...f, run_id: "" }));
      load();
    } catch (ex) {
      setErr(ex.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="card">
        <h2>Launch a QC run</h2>
        <form className="row" onSubmit={launch}>
          <input
            placeholder="run name, e.g. qc-2026-09"
            value={form.run_id}
            onChange={(e) => setForm({ ...form, run_id: e.target.value })}
          />
          <select value={form.input} onChange={(e) => setForm({ ...form, input: e.target.value })}>
            {inputs.map((i) => (
              <option key={i.name} value={i.name}>
                {i.name === "." ? "staged/ (root)" : i.name} — {i.subjects} subjects
              </option>
            ))}
          </select>
          <label className="check">
            <input
              type="checkbox"
              checked={form.render}
              onChange={(e) => setForm({ ...form, render: e.target.checked })}
            />
            render figures
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.review}
              onChange={(e) => setForm({ ...form, review: e.target.checked })}
            />
            agent figure review
          </label>
          <button className="primary" disabled={busy || !form.run_id || !form.input}>
            Launch
          </button>
        </form>
        {!inputs.length && (
          <p className="pill" style={{ marginTop: 8 }}>
            No staged inputs found — copy an fMRIPrep light subset into <span className="mono">staged/</span>{" "}
            (see <span className="mono">stage_inputs.py</span>).
          </p>
        )}
        {err && <p className="err">{err}</p>}
      </div>

      <div className="card">
        <h2>Runs</h2>
        {!runs && <p className="pill">Loading…</p>}
        {runs && !runs.length && <p className="pill">No runs yet.</p>}
        {runs && runs.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Created</th>
                <th>Job</th>
                <th className="num">Scans</th>
                <th className="num">Include</th>
                <th className="num">Caution</th>
                <th className="num">Exclude</th>
                <th className="num">Verify</th>
                <th className="num">Decided</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} onClick={() => onOpen(r.run_id)}>
                  <td><b>{r.run_id}</b></td>
                  <td className="pill">{r.created}</td>
                  <td>
                    {ACTIVE.includes(r.job.phase) && <span className="spin" style={{ marginRight: 6 }} />}
                    <span className={r.job.phase === "failed" ? "err" : "pill"}>{r.job.phase}</span>
                  </td>
                  <td className="num">{r.n_scans}</td>
                  <td className="num" style={{ color: "var(--include)" }}>{r.counts.INCLUDE || 0}</td>
                  <td className="num" style={{ color: "var(--caution)" }}>{r.counts.CAUTION || 0}</td>
                  <td className="num" style={{ color: "var(--exclude)" }}>{r.counts.EXCLUDE || 0}</td>
                  <td className="num" style={{ color: "var(--verify)" }}>{r.n_verify}</td>
                  <td className="num">{r.n_decided}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
