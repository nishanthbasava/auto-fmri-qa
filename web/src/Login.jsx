import { useState } from "react";
import { api, setToken, clearToken } from "./api.js";

export default function Login({ onDone }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setToken(pw);
    try {
      await api("/api/runs"); // any authed endpoint validates the password
      onDone();
    } catch (ex) {
      clearToken();
      setErr(ex.message === "unauthorized" ? "Wrong password" : `Server error: ${ex.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <h1>auto-fmri-qa</h1>
        <p>fMRIPrep quality-control review. Enter the lab password.</p>
        <input
          type="password"
          placeholder="Lab password"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          autoFocus
        />
        <button className="primary" disabled={busy || !pw}>
          {busy ? "Checking…" : "Enter"}
        </button>
        {err && <p className="err" style={{ marginTop: 10 }}>{err}</p>}
      </form>
    </div>
  );
}
