import { useEffect, useState } from "react";
import { clearToken, getToken, setUnauthorizedHandler } from "./api.js";
import Login from "./Login.jsx";
import RunsPage from "./RunsPage.jsx";
import RunDetail from "./RunDetail.jsx";

// Tiny hash router: "#/" = runs list, "#/run/<id>" = run detail.
const parse = () => {
  const m = window.location.hash.match(/^#\/run\/([A-Za-z0-9._-]+)/);
  return m ? { page: "run", runId: m[1] } : { page: "runs" };
};

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [route, setRoute] = useState(parse());

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false));
    const onHash = () => setRoute(parse());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  return (
    <>
      <div className="topbar">
        <h1
          className="crumb"
          onClick={() => { window.location.hash = "#/"; }}
        >
          auto-fmri-qa
        </h1>
        {route.page === "run" && <span className="pill">/ {route.runId}</span>}
        <div className="spacer" />
        <button
          className="ghost"
          onClick={() => { clearToken(); setAuthed(false); }}
        >
          log out
        </button>
      </div>
      {route.page === "runs" && (
        <RunsPage onOpen={(id) => { window.location.hash = `#/run/${id}`; }} />
      )}
      {route.page === "run" && (
        <RunDetail runId={route.runId} onBack={() => { window.location.hash = "#/"; }} />
      )}
    </>
  );
}
