import { useState } from "react";
import { login } from "./api.js";

export default function Login({ onDone }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const user = await login(username.trim(), password);
      onDone(user);
    } catch (ex) {
      setErr(ex.message === "bad username or password" ? "Wrong username or password" : ex.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <h1>auto-fmri-qa</h1>
        <p>fMRIPrep quality-control review. Sign in with your lab account.</p>
        <input
          id="login-username"
          placeholder="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <input
          id="login-password"
          type="password"
          placeholder="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button className="primary" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {err && <p className="err" style={{ marginTop: 10 }}>{err}</p>}
        <p className="pill" style={{ marginTop: 12 }}>
          No account yet? An admin creates one with{" "}
          <span className="mono">autoqa users add &lt;name&gt; --role reviewer</span>.
        </p>
      </form>
    </div>
  );
}
