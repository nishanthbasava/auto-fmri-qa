// Thin fetch wrapper. After login the JWT and the user's {username, role} are
// kept in sessionStorage (cleared when the tab closes) and the token is sent
// as a Bearer header on every request; a 401 clears it and bounces the app
// back to the login screen.

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export const getToken = () => sessionStorage.getItem("afq_token") || "";
export const getUser = () => {
  try { return JSON.parse(sessionStorage.getItem("afq_user") || "null"); } catch { return null; }
};
export const setSession = (token, user) => {
  sessionStorage.setItem("afq_token", token);
  sessionStorage.setItem("afq_user", JSON.stringify(user));
};
export const clearSession = () => {
  sessionStorage.removeItem("afq_token");
  sessionStorage.removeItem("afq_user");
};

// Role hierarchy mirrors the API: viewer < reviewer < admin.
const ROLES = ["viewer", "reviewer", "admin"];
export const can = (user, role) => !!user && ROLES.indexOf(user.role) >= ROLES.indexOf(role);

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      Authorization: `Bearer ${getToken()}`,
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    clearSession();
    onUnauthorized();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

export async function login(username, password) {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    let detail = "login failed";
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  const data = await res.json();
  setSession(data.token, data.user);
  return data.user;
}

// <img> tags cannot send an Authorization header, so figures are fetched as
// blobs and handed to the component as object URLs (caller must revoke).
export async function fetchImage(path) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new Error(`figure ${res.status}`);
  return URL.createObjectURL(await res.blob());
}
