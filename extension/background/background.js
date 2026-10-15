/* MV3 service worker: badge count, polling, notifications, job cache.
   Keeps progress alive when popup is closed. */
const ext = (typeof browser !== "undefined" && browser?.runtime) ? browser : chrome;
const POLL_MS = 2500;
let polling = false;
let notified = {}; // job_id -> terminal status already notified

async function getSettings() {
  if (typeof YTDL !== "undefined" && YTDL.getSettings) return YTDL.getSettings();
  const d = await ext.storage.local.get(["serverUrl", "token", "trackedJobs", "jobCache"]);
  return {
    serverUrl: d.serverUrl || "http://127.0.0.1:8765",
    token: d.token || "",
    trackedJobs: d.trackedJobs || [],
    jobCache: d.jobCache || {}
  };
}

async function fetchActive() {
  const s = await getSettings();
  if (!s.token) return null;
  const base = (s.serverUrl || "http://127.0.0.1:8765").replace(/\/+$/, "");
  try {
    const res = await fetch(base + "/jobs?active_only=true", {
      headers: { "Authorization": "Bearer " + s.token }
    });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

async function fetchJob(jobId) {
  const s = await getSettings();
  const base = (s.serverUrl || "http://127.0.0.1:8765").replace(/\/+$/, "");
  try {
    const res = await fetch(base + "/jobs/" + encodeURIComponent(jobId), {
      headers: { "Authorization": "Bearer " + s.token }
    });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

async function pollOnce() {
  if (polling) return;
  polling = true;
  try {
    const s = await getSettings();
    const tracked = s.trackedJobs || [];
    const cache = s.jobCache || {};
    let active = 0;

    // Refresh every tracked job (so popup reopen shows latest state)
    for (const jobId of tracked.slice(-20)) {
      const j = await fetchJob(jobId);
      if (j) {
        cache[jobId] = { ...j, updatedAt: Date.now() };
        if (["queued", "downloading", "merging"].includes(j.status)) active++;
        const terminal = ["completed", "error", "cancelled"].includes(j.status);
        if (terminal && notified[jobId] !== j.status) {
          notified[jobId] = j.status;
          notifyJob(j);
        }
      }
    }
    // Also count server-side active (covers jobs started elsewhere)
    const snap = await fetchActive();
    if (snap && typeof snap.active === "number") active = Math.max(active, snap.active);

    await ext.storage.local.set({ jobCache: cache });
    await setBadge(active);

    // Prune tracked list to last 20
    if (tracked.length > 20) {
      await ext.storage.local.set({ trackedJobs: tracked.slice(-20) });
    }
  } finally {
    polling = false;
  }
}

async function setBadge(n) {
  try {
    const text = n > 0 ? String(n) : "";
    if (ext.action?.setBadgeText) await ext.action.setBadgeText({ text });
    if (ext.action?.setBadgeBackgroundColor)
      await ext.action.setBadgeBackgroundColor({ color: "#e11d48" });
  } catch {}
}

function notifyJob(j) {
  try {
    const title = j.current_title || "YouTube download";
    if (j.status === "completed") {
      ext.notifications?.create("ytdl-" + j.job_id + "-done", {
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: "Download finished",
        message: title.slice(0, 120)
      });
    } else if (j.status === "error") {
      ext.notifications?.create("ytdl-" + j.job_id + "-err", {
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: "Download failed",
        message: (j.error || title).slice(0, 160)
      });
    }
  } catch {}
}

ext.runtime.onInstalled.addListener(async () => {
  const cur = await ext.storage.local.get(null);
  const defaults = {
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
  const patch = {};
  for (const [k, v] of Object.entries(defaults)) if (!(k in cur)) patch[k] = v;
  if (Object.keys(patch).length) await ext.storage.local.set(patch);
  setBadge(0);
});

ext.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (!msg || !msg.type) return sendResponse({});
    if (msg.type === "TRACK_JOB" && msg.job_id) {
      const d = await ext.storage.local.get(["trackedJobs"]);
      const t = d.trackedJobs || [];
      if (!t.includes(msg.job_id)) {
        t.push(msg.job_id);
        await ext.storage.local.set({ trackedJobs: t.slice(-20) });
      }
      pollOnce();
      sendResponse({ ok: true });
    } else if (msg.type === "YT_URL_CLICKED" && msg.url) {
      await ext.storage.local.set({ pendingUrl: msg.url });
      // Try to open the popup (Chrome 116+); fall back silently.
      try {
        if (ext.action?.openPopup) await ext.action.openPopup();
      } catch {}
      sendResponse({ ok: true });
    } else if (msg.type === "POLL_NOW") {
      await pollOnce();
      sendResponse({ ok: true });
    } else {
      sendResponse({});
    }
  })();
  return true; // async response
});

// Keep polling alive: interval + alarm (alarm wakes a killed SW).
setInterval(pollOnce, POLL_MS);
try {
  ext.alarms?.create("ytdl-poll", { periodInMinutes: 0.5 });
  ext.alarms?.onAlarm.addListener((a) => { if (a?.name === "ytdl-poll") pollOnce(); });
} catch {}
pollOnce();
