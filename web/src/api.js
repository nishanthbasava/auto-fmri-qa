// Thin fetch wrapper. The shared lab password is kept in sessionStorage and
// sent as a Bearer token on every request; a 401 clears it and bounces the
// app back to the login screen.

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export const getToken = () => sessionStorage.getItem("afq_token") || "";
export const setToken = (t) => sessionStorage.setItem("afq_token", t);
export const clearToken = () => sessionStorage.removeItem("afq_token");

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
    clearToken();
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

// <img> tags cannot send an Authorization header, so figures are fetched as
// blobs and handed to the component as object URLs (caller must revoke).
export async function fetchImage(path) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new Error(`figure ${res.status}`);
  return URL.createObjectURL(await res.blob());
}
