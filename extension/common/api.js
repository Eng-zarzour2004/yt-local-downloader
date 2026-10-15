/* Shared helpers for popup / options / background / content.
   Works in Chrome (chrome.*) and Firefox (browser.*). No build step. */
(function (global) {
  const ext = (typeof browser !== "undefined" && browser?.runtime) ? browser : chrome;

  const DEFAULTS = {
    serverUrl: "http://127.0.0.1:8765",
    token: "",
    defaultQuality: "1080",
    defaultContainer: "mp4",
    defaultAudioFormat: "mp3",
    defaultAudioBitrate: "192",
    downloadFolder: "",
    maxConcurrent: 2,
    pendingUrl: "",
    trackedJobs: [],
    jobCache: {}
  };

  async function getSettings() {
    try {
      const s = await ext.storage.local.get(Object.keys(DEFAULTS));
      return { ...DEFAULTS, ...s };
    } catch (e) {
      return { ...DEFAULTS };
    }
  }

  async function setSettings(patch) {
    await ext.storage.local.set(patch);
  }

  function normalizeServerUrl(u) {
    u = (u || "").trim().replace(/\/+$/, "");
    if (!u) return "http://127.0.0.1:8765";
    if (!/^https?:\/\//i.test(u)) u = "http://" + u;
    return u.replace(/\/+$/, "");
  }

  function isYouTubeUrl(u) {
    if (!u) return false;
    try {
      const url = new URL(u);
      const h = url.hostname.replace(/^m\./, "").replace(/^www\./, "");
      if (h === "youtu.be") return true;
      if (h === "youtube.com" || h.endsWith(".youtube.com")) {
        return url.pathname.startsWith("/watch") || url.pathname.startsWith("/shorts") ||
               url.pathname.startsWith("/playlist") || url.searchParams.has("v") ||
               url.searchParams.has("list");
      }
      return false;
    } catch { return false; }
  }

  async function apiFetch(path, { method = "GET", body = null, auth = true } = {}) {
    const s = await getSettings();
    const base = normalizeServerUrl(s.serverUrl);
    const headers = { "Content-Type": "application/json" };
    if (auth && s.token) headers["Authorization"] = "Bearer " + s.token;
    const res = await fetch(base + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null
    });
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      const msg = (data && (data.detail || data.error)) || ("HTTP " + res.status);
      const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function sseUrl(jobId, serverUrl, token) {
    return normalizeServerUrl(serverUrl) + "/progress/" + encodeURIComponent(jobId) +
           "?token=" + encodeURIComponent(token || "");
  }

  global.YTDL = { ext, DEFAULTS, getSettings, setSettings, normalizeServerUrl, isYouTubeUrl, apiFetch, sseUrl };
})(typeof window !== "undefined" ? window : globalThis);
