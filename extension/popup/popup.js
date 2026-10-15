/* Popup: auto-detect URL, /info preview, format picker, SSE+polling progress,
   queue + history tabs. Survives popup close via background job cache. */
(function () {
  const { ext, getSettings, apiFetch, sseUrl, isYouTubeUrl } = window.YTDL;
  const $ = (id) => document.getElementById(id);

  let currentInfo = null;
  let currentJobId = null;
  let eventSource = null;
  let pollTimer = null;

  // ---------- tabs ----------
  document.querySelectorAll(".tab").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      $("tab-" + b.dataset.tab).classList.add("active");
      if (b.dataset.tab === "queue") renderQueue();
      if (b.dataset.tab === "history") renderHistory();
    });
  });
  $("openOptions").addEventListener("click", () => ext.runtime.openOptionsPage());

  // ---------- init ----------
  init();
  async function init() {
    await checkHealth();
    const url = await detectUrl();
    if (url) {
      $("urlInput").value = url;
      $("autoHint").textContent = "Detected from current tab.";
      fetchInfo(url);
    } else {
      const s = await getSettings();
      if (s.pendingUrl && isYouTubeUrl(s.pendingUrl)) {
        $("urlInput").value = s.pendingUrl;
        $("autoHint").textContent = "From the page Download button.";
        fetchInfo(s.pendingUrl);
      } else {
        $("autoHint").textContent = "Open a YouTube video, or paste a URL.";
      }
    }
    // Resume last tracked job progress (popup was closed mid-download)
    const s = await getSettings();
    const tracked = s.trackedJobs || [];
    if (tracked.length) {
      const lastId = tracked[tracked.length - 1];
      const cached = (s.jobCache || {})[lastId];
      if (cached && ["queued", "downloading", "merging"].includes(cached.status)) {
        resumeJob(lastId);
      }
    }
    renderQueue();
    renderHistory();
    setInterval(checkHealth, 15000);
  }

  async function detectUrl() {
    try {
      const tabs = await ext.tabs.query({ active: true, currentWindow: true });
      const u = tabs?.[0]?.url || "";
      return isYouTubeUrl(u) ? u : "";
    } catch { return ""; }
  }

  async function checkHealth() {
    const dot = $("serverDot"), line = $("statusLine");
    try {
      const s = await getSettings();
      const base = (s.serverUrl || "http://127.0.0.1:8765").replace(/\/+$/, "");
      const res = await fetch(base + "/health");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const h = await res.json();
      const authed = !!s.token;
      dot.className = "server-dot " + (h.status === "ok" ? "green" : "red");
      line.textContent = authed
        ? `Companion v${h.ytdlp_version || "?"} · ffmpeg ${h.ffmpeg ? "OK" : "MISSING"} · ${h.active_downloads ?? 0} active`
        : "Companion reachable — set your API token in Options ⚙";
      if (!h.ffmpeg) line.textContent += " — ffmpeg MISSING (see README)";
    } catch {
      dot.className = "server-dot red";
      line.textContent = "Companion not running — start it (run.bat / run.sh), then Test connection in Options.";
    }
  }

  // ---------- info ----------
  $("fetchBtn").addEventListener("click", () => {
    const u = $("urlInput").value.trim();
    if (!u) return showError("Paste a YouTube URL first.");
    fetchInfo(u);
  });
  $("urlInput").addEventListener("change", () => {
    const u = $("urlInput").value.trim();
    if (isYouTubeUrl(u)) fetchInfo(u);
  });
  $("audioOnly").addEventListener("change", () => {
    $("audioOpts").classList.toggle("hidden", !$("audioOnly").checked);
  });

  async function fetchInfo(url) {
    hideError();
    $("preview").classList.add("hidden");
    $("formatSection").classList.add("hidden");
    $("playlistBox").classList.add("hidden");
    document.querySelector('input[name="plScope"][value="single"]').disabled = false;
    $("autoHint").textContent = "Loading video info…";
    try {
      const info = await apiFetch("/info", { method: "POST", body: { url } });
      currentInfo = info;
      renderInfo(info);
      $("autoHint").textContent = "";
    } catch (e) {
      currentInfo = null;
      showError("Could not fetch video info.\n" + compassError(e));
    }
  }

  function compassError(e) {
    let m = e?.message || String(e);
    if (e?.status === 0 || /Failed to fetch|NetworkError/i.test(m)) {
      return "Cannot reach companion. Is it running on 127.0.0.1:8765? Check Options → Test connection.";
    }
    if (e?.status === 401) return "Invalid API token. Copy the token printed by the companion console into Options.";
    return m;
  }

  function renderInfo(info) {
    $("preview").classList.remove("hidden");
    $("pvTitle").textContent = info.title || "Unknown";
    const sub = info.is_playlist
      ? `Playlist · ${info.playlist_count ?? (info.entries || []).length} videos`
      : `${info.channel || ""} · ${info.duration_string || ""}`;
    $("pvSub").textContent = sub;
    if (info.thumbnail) { $("pvThumb").src = info.thumbnail; $("pvThumb").style.display = ""; }
    else $("pvThumb").style.display = "none";

    if (info.is_playlist) {
      // Pure playlist URL: whole-playlist scope only.
      $("playlistBox").classList.remove("hidden");
      const pl = info.playlist || {};
      document.querySelector('input[name="plScope"][value="full"]').checked = true;
      document.querySelector('input[name="plScope"][value="single"]').disabled = true;
      $("playlistLabel").textContent = `"${pl.title || info.playlist_title || "Playlist"}" — ${pl.count ?? info.playlist_count ?? info.entries?.length ?? "?"} videos. The whole playlist will be queued with per-item progress.`;
    } else if (info.playlist) {
      // watch?v=...&list=... : this video belongs to a playlist — offer both scopes.
      $("playlistBox").classList.remove("hidden");
      document.querySelector('input[name="plScope"][value="single"]').disabled = false;
      document.querySelector('input[name="plScope"][value="single"]').checked = true;
      $("playlistLabel").textContent = `Part of playlist "${info.playlist.title}" (${info.playlist.count ?? "?"} videos). Download just this video or queue the whole playlist.`;
    }

    // Quality picker: only options that actually exist
    const s = window._lastSettings;
    fillQuality(info.quality_options || []);
    $("formatSection").classList.remove("hidden");
  }

  async function fillQuality(options) {
    const sel = $("qualitySel");
    sel.innerHTML = "";
    const settings = await getSettings();
    window._lastSettings = settings;
    const defQ = settings.defaultQuality || "1080";
    // Always include Best + standard ladder; disable missing ones.
    const order = ["best", "2160", "1440", "1080", "720", "480"];
    const byVal = Object.fromEntries((options || []).map((o) => [String(o.value), o]));
    for (const v of order) {
      const o = byVal[v] || { value: v, label: v === "best" ? "Best available" : v + "p", available: true };
      const el = document.createElement("option");
      el.value = String(o.value);
      el.textContent = o.label + (o.available === false ? " (unavailable)" : "");
      el.disabled = o.available === false;
      sel.appendChild(el);
    }
    if ([...sel.options].some((o) => o.value === defQ && !o.disabled)) sel.value = defQ;
    else sel.value = "best";
    $("containerSel").value = settings.defaultContainer || "mp4";
    $("audioFmt").value = settings.defaultAudioFormat || "mp3";
    $("audioBr").value = settings.defaultAudioBitrate || "192";
  }

  function showError(msg) {
    const b = $("errorBox");
    b.textContent = msg;
    b.classList.remove("hidden");
  }
  function hideError() { $("errorBox").classList.add("hidden"); }

  // ---------- download ----------
  $("downloadBtn").addEventListener("click", async () => {
    hideError();
    const url = $("urlInput").value.trim();
    if (!isYouTubeUrl(url)) return showError("Invalid URL. Paste a youtube.com/watch, youtu.be, /shorts, or playlist URL.");
    const audioOnly = $("audioOnly").checked;
    const scope = document.querySelector('input[name="plScope"]:checked')?.value || "single";
    const wantPlaylist = !!(currentInfo?.is_playlist || (currentInfo?.playlist && scope === "full"));
    const body = {
      url,
      quality: audioOnly ? "best" : $("qualitySel").value,
      container: $("containerSel").value,
      audio_only: audioOnly,
      audio_format: $("audioFmt").value,
      audio_bitrate: $("audioBr").value,
      download_playlist: wantPlaylist,
      playlist_url: wantPlaylist
        ? (currentInfo?.is_playlist ? (currentInfo?.playlist?.url || url) : (currentInfo?.playlist?.url || undefined))
        : undefined
    };
    $("downloadBtn").disabled = true;
    try {
      const res = await apiFetch("/download", { method: "POST", body });
      const jobId = res.job_id;
      try { await ext.runtime.sendMessage({ type: "TRACK_JOB", job_id: jobId }); } catch {}
      try { await ext.storage.local.set({ pendingUrl: "" }); } catch {}
      resumeJob(jobId);
    } catch (e) {
      showError(compassError(e));
    } finally {
      $("downloadBtn").disabled = false;
    }
  });

  function resumeJob(jobId) {
    currentJobId = jobId;
    $("formatSection").classList.add("hidden");
    $("progressBox").classList.remove("hidden");
    startSSE(jobId);
    startPollFallback(jobId);
  }

  function startSSE(jobId) {
    stopSSE();
    getSettings().then((s) => {
      try {
        eventSource = new EventSource(sseUrl(jobId, s.serverUrl, s.token));
        eventSource.onmessage = (ev) => {
          try { renderProgress(JSON.parse(ev.data)); } catch {}
        };
        eventSource.onerror = () => { /* polling fallback keeps UI alive */ };
      } catch {}
    });
  }
  function stopSSE() { try { eventSource?.close(); } catch {} eventSource = null; }

  function startPollFallback(jobId) {
    clearInterval(pollTimer);
    const tick = async () => {
      try {
        const j = await apiFetch("/jobs/" + encodeURIComponent(jobId));
        renderProgress(j);
        try { await ext.runtime.sendMessage({ type: "POLL_NOW" }); } catch {}
        if (["completed", "error", "cancelled"].includes(j.status)) clearInterval(pollTimer);
      } catch {}
    };
    tick();
    pollTimer = setInterval(tick, 2000);
  }

  function renderProgress(j) {
    if (!j || (currentJobId && j.job_id !== currentJobId)) {
      // Still update queue badge count
      renderQueue(true);
      return;
    }
    const pct = Math.max(0, Math.min(100, j.percent || 0));
    $("progPct").textContent = pct.toFixed(1) + "%";
    $("progFill").style.width = pct + "%";
    $("progSpeed").textContent = j.speed_str || "";
    $("progEta").textContent = j.eta_str || "";
    const title = j.current_title || "Working…";
    if (j.status === "completed") $("progLabel").textContent = "✓ Done: " + title;
    else if (j.status === "error") $("progLabel").textContent = "✕ Failed";
    else if (j.status === "cancelled") $("progLabel").textContent = "Cancelled";
    else if (j.status === "merging") $("progLabel").textContent = "Merging with ffmpeg… " + title;
    else $("progLabel").textContent = (j.total_items > 1 ? `[${(j.current_index ?? 0) + 1}/${j.total_items}] ` : "") + title;

    if (j.status === "error" && j.error) showError(j.error);

    const box = $("queueItems");
    box.innerHTML = "";
    if (j.total_items > 1) {
      for (const it of j.items || []) {
        const d = document.createElement("div");
        d.className = "qitem";
        d.innerHTML = `<div class="t"></div><div class="s"></div>`;
        d.querySelector(".t").textContent = `${(it.index ?? 0) + 1}. ${it.title || it.url}`;
        d.querySelector(".s").textContent = `${it.status}${it.status === "downloading" ? " · " + (it.percent || 0).toFixed(0) + "%" : ""}${it.error ? " — " + it.error : ""}`;
        box.appendChild(d);
      }
    }
    renderQueue(true);
    if (["completed", "error", "cancelled"].includes(j.status)) {
      stopSSE();
      renderHistory();
    }
  }

  $("cancelBtn").addEventListener("click", async () => {
    if (!currentJobId) return;
    try { await apiFetch("/cancel/" + encodeURIComponent(currentJobId), { method: "POST" }); } catch (e) {
      showError(compassError(e));
    }
  });
  $("newBtn").addEventListener("click", () => {
    stopSSE(); clearInterval(pollTimer);
    currentJobId = null;
    $("progressBox").classList.add("hidden");
    if (currentInfo) $("formatSection").classList.remove("hidden");
  });

  // ---------- queue tab ----------
  async function renderQueue(silent) {
    try {
      const res = await apiFetch("/jobs?active_only=false");
      const jobs = (res.jobs || []).slice().reverse();
      const active = jobs.filter((j) => ["queued", "downloading", "merging"].includes(j.status));
      const pill = $("queueCount");
      if (active.length) { pill.textContent = active.length; pill.classList.remove("hidden"); }
      else pill.classList.add("hidden");
      const list = $("queueList");
      if (!jobs.length) { list.innerHTML = '<div class="hint">No downloads yet.</div>'; return; }
      list.innerHTML = "";
      for (const j of jobs.slice(0, 15)) {
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `<div class="t"></div><div class="s"></div><div class="ops"></div>`;
        card.querySelector(".t").textContent = j.current_title || j.url;
        card.querySelector(".s").textContent = `${j.status} · ${(j.percent || 0).toFixed(1)}% ${j.speed_str || ""} ${j.eta_str || ""}`;
        const ops = card.querySelector(".ops");
        const view = document.createElement("button");
        view.className = "mini"; view.textContent = "View";
        view.addEventListener("click", () => {
          document.querySelector('[data-tab="download"]').click();
          resumeJob(j.job_id);
        });
        ops.appendChild(view);
        if (["queued", "downloading", "merging"].includes(j.status)) {
          const c = document.createElement("button");
          c.className = "mini warn"; c.textContent = "Cancel";
          c.addEventListener("click", async () => {
            await apiFetch("/cancel/" + encodeURIComponent(j.job_id), { method: "POST" });
            renderQueue();
          });
          ops.appendChild(c);
        }
        list.appendChild(card);
      }
    } catch { if (!silent) $("queueList").innerHTML = '<div class="hint">Companion unreachable.</div>'; }
  }

  // ---------- history tab ----------
  $("refreshHist").addEventListener("click", renderHistory);
  async function renderHistory() {
    const list = $("historyList");
    try {
      const res = await apiFetch("/history?limit=50");
      const items = res.history || [];
      if (!items.length) { list.innerHTML = '<div class="hint">No downloads yet.</div>'; return; }
      list.innerHTML = "";
      for (const h of items) {
        const card = document.createElement("div");
        card.className = "card";
        const when = (h.completed_at || h.created_at || "").replace("T", " ").slice(0, 16);
        card.innerHTML = `<div class="t"></div><div class="s"></div><div class="ops"></div>`;
        card.querySelector(".t").textContent = h.title || h.url;
        card.querySelector(".s").textContent =
          `${h.quality || ""} ${h.container || ""} · ${h.status}${h.filesize ? " · " + fmtBytes(h.filesize) : ""} · ${when}${h.file_exists === false ? " · file missing" : ""}`;
        const ops = card.querySelector(".ops");
        const mk = (label, cls, fn) => {
          const b = document.createElement("button");
          b.className = "mini " + (cls || ""); b.textContent = label;
          b.addEventListener("click", fn);
          ops.appendChild(b);
        };
        mk("Re-download", "", async () => {
          const r = await apiFetch(`/history/${h.id}/redownload`, { method: "POST" });
          try { await ext.runtime.sendMessage({ type: "TRACK_JOB", job_id: r.job_id }); } catch {}
          document.querySelector('[data-tab="download"]').click();
          resumeJob(r.job_id);
        });
        mk("Open folder", "", () => apiFetch(`/history/${h.id}/reveal`, { method: "POST" }).catch((e) => showError(compassError(e))));
        mk("Delete file", "warn", async () => {
          if (!confirm("Delete the file from disk and remove history entry?")) return;
          await apiFetch(`/history/${h.id}?delete_file=true`, { method: "DELETE" });
          renderHistory();
        });
        list.appendChild(card);
      }
    } catch {
      list.innerHTML = '<div class="hint">Companion unreachable — start it and set the token in Options.</div>';
    }
  }

  function fmtBytes(n) {
    n = Number(n || 0);
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
    return (n / 1024 / 1024 / 1024).toFixed(2) + " GB";
  }
})();
