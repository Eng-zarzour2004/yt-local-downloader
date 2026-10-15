/* Options page: load/save + Test connection + Update yt-dlp. */
(function () {
  const { getSettings, setSettings, normalizeServerUrl, apiFetch } = window.YTDL;
  const $ = (id) => document.getElementById(id);

  init();
  async function init() {
    const s = await getSettings();
    $("serverUrl").value = s.serverUrl || "http://127.0.0.1:8765";
    $("token").value = s.token || "";
    $("defaultQuality").value = s.defaultQuality || "1080";
    $("defaultContainer").value = s.defaultContainer || "mp4";
    $("defaultAudioFormat").value = s.defaultAudioFormat || "mp3";
    $("defaultAudioBitrate").value = s.defaultAudioBitrate || "192";
    $("maxConcurrent").value = s.maxConcurrent || 2;
    $("downloadFolder").value = s.downloadFolder || "";
    // Pull server-side folder if empty
    try {
      if (s.token) {
        const cur = await apiFetch("/settings");
        if (!($("downloadFolder").value || "").trim() && cur.download_dir) {
          $("downloadFolder").value = cur.download_dir;
        }
        if (cur.max_concurrent) $("maxConcurrent").value = cur.max_concurrent;
      }
    } catch {}
  }

  $("saveBtn").addEventListener("click", async () => {
    const patch = {
      serverUrl: normalizeServerUrl($("serverUrl").value),
      token: $("token").value.trim(),
      defaultQuality: $("defaultQuality").value,
      defaultContainer: $("defaultContainer").value,
      defaultAudioFormat: $("defaultAudioFormat").value,
      defaultAudioBitrate: $("defaultAudioBitrate").value,
      maxConcurrent: Math.max(1, Math.min(5, parseInt($("maxConcurrent").value || "2", 10))),
      downloadFolder: $("downloadFolder").value.trim()
    };
    await setSettings(patch);
    // Push server-side settings (folder + concurrency)
    try {
      await apiFetch("/settings", { method: "POST", body: {
        download_dir: patch.downloadFolder || undefined,
        max_concurrent: patch.maxConcurrent
      }});
      $("saveText").textContent = "Saved ✓ (server updated)";
    } catch (e) {
      $("saveText").textContent = "Saved locally; server update failed: " + (e.message || e).slice(0, 120);
    }
    setTimeout(() => ($("saveText").textContent = ""), 3000);
  });

  $("testBtn").addEventListener("click", async () => {
    const dot = $("connDot"), txt = $("connText"), det = $("connDetail");
    dot.className = "dot unknown"; txt.textContent = "Testing…"; det.textContent = "";
    const base = normalizeServerUrl($("serverUrl").value);
    // 1) server reachable? (no auth)
    try {
      const res = await fetch(base + "/health");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const h = await res.json();
      // 2) auth + settings?
      try {
        const token = $("token").value.trim();
        const r2 = await fetch(base + "/settings", {
          headers: token ? { "Authorization": "Bearer " + token } : {}
        });
        if (r2.status === 401) throw new Error("auth");
        if (!r2.ok) throw new Error("HTTP " + r2.status);
        const s = await r2.json();
        dot.className = "dot green";
        txt.textContent = "Connected ✓";
        det.textContent = `Companion OK · ffmpeg ${h.ffmpeg ? "found (" + (h.ffmpeg_version || "") + ")" : "MISSING — install ffmpeg"} · yt-dlp ${h.ytdlp_version || "?"} · folder: ${s.download_dir}`;
      } catch (e2) {
        dot.className = "dot red";
        txt.textContent = e2.message === "auth" ? "Server OK, token invalid" : "Server OK, auth check failed";
        det.textContent = e2.message === "auth"
          ? "The companion is running, but the token is wrong. Copy the token from the companion console output."
          : String(e2.message || e2);
      }
    } catch (e) {
      dot.className = "dot red";
      txt.textContent = "Unreachable";
      det.textContent = "Cannot reach " + base + "/health. Start the companion (run.bat / run.sh) and check the port. " + (e.message || e);
    }
  });

  $("updateBtn").addEventListener("click", async () => {
    $("updateText").textContent = "Updating…";
    try {
      const r = await apiFetch("/update-ytdlp", { method: "POST" });
      $("updateText").textContent = "✓ yt-dlp " + (r.ytdlp_version || "updated") + " — restart companion if version looks old.";
    } catch (e) {
      $("updateText").textContent = "Failed: " + (e.message || e).slice(0, 200);
    }
  });
})();
