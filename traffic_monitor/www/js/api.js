// Thin fetch wrapper for /api/*.
//
// IMPORTANT: every URL here is relative with NO leading slash. Home
// Assistant serves ingress add-ons under a per-session token prefix
// (".../api/hassio_ingress/<token>/"), and the browser resolves a
// relative URL like "api/routes" against the *current page's* URL --
// which correctly includes that prefix. A root-relative URL like
// "/api/routes" would instead resolve against Home Assistant's own
// top-level origin, missing the ingress proxy entirely. This page is
// always served at a URL ending in "/", so relative resolution works;
// don't "simplify" any of these by adding a leading slash.
const Api = (() => {
  async function request(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(path, opts);
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const errBody = await resp.json();
        detail = errBody.detail || detail;
      } catch {
        // non-JSON error body -- fall back to statusText
      }
      const err = new Error(detail);
      err.status = resp.status;
      throw err;
    }
    if (resp.status === 204) return null;
    return resp.json();
  }

  return {
    status: () => request("GET", "api/status"),
    usage: () => request("GET", "api/usage"),
    listRoutes: () => request("GET", "api/routes"),
    allRouteStatus: () => request("GET", "api/routes/status"),
    getRoute: (id) => request("GET", `api/routes/${encodeURIComponent(id)}`),
    createRoute: (body) => request("POST", "api/routes", body),
    updateRoute: (id, body) => request("PUT", `api/routes/${encodeURIComponent(id)}`, body),
    deleteRoute: (id) => request("DELETE", `api/routes/${encodeURIComponent(id)}`),
    previewRoute: (body) => request("POST", "api/routes/preview", body),
  };
})();
