import { useEffect, useState } from "react";
import { clearSession, getToken, getUser, setUnauthorizedHandler } from "./api.js";
import Login from "./Login.jsx";
import RunsPage from "./RunsPage.jsx";
import RunDetail from "./RunDetail.jsx";

// Tiny hash router: "#/" = runs list, "#/run/<id>" = run detail.
const parse = () => {
  const m = window.location.hash.match(/^#\/run\/([A-Za-z0-9._-]+)/);
  return m ? { page: "run", runId: m[1] } : { page: "runs" };
};

export default function App() {
  const [user, setUser] = useState(getToken() ? getUser() : null);
  const [route, setRoute] = useState(parse());

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    const onHash = () => setRoute(parse());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (!user) return <Login onDone={setUser} />;

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
        <span className="pill">
          <b>{user.username}</b> · {user.role}
        </span>
        <button
          className="ghost"
          onClick={() => { clearSession(); setUser(null); }}
        >
          sign out
        </button>
      </div>
      {route.page === "runs" && (
        <RunsPage user={user} onOpen={(id) => { window.location.hash = `#/run/${id}`; }} />
      )}
      {route.page === "run" && (
        <RunDetail
          user={user}
          runId={route.runId}
          onBack={() => { window.location.hash = "#/"; }}
        />
      )}
    </>
  );
}
