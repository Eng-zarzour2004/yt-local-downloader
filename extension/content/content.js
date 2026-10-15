/* Content script: inject a "Download" button on watch / shorts pages.
   Handles YouTube SPA navigation via yt-navigate-finish + MutationObserver. */
(function () {
  const ext = (typeof browser !== "undefined" && browser?.runtime) ? browser : chrome;
  const BTN_ID = "ytdl-local-download-btn";
  const TOAST_ID = "ytdl-local-toast";

  function currentUrl() {
    return location.href;
  }

  function isVideoPage() {
    return /\/watch|\/shorts(\/|$)/.test(location.pathname);
  }

  function findActionContainer() {
    // Preferred: the actions row next to like/dislike/share.
    const selectors = [
      "#actions-inner",
      "ytd-watch-metadata #actions",
      "#top-level-buttons-computed",
      "ytd-menu-renderer.ytd-watch-metadata",
      "#actions ytd-menu-renderer"
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function ensureButton() {
    if (!isVideoPage()) return;
    if (document.getElementById(BTN_ID)) return;
    const container = findActionContainer();
    if (!container) return;

    const btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.type = "button";
    btn.title = "Download via local companion";
    btn.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 3v12.17l4.59-4.58L18 12l-6 6-6-6 1.41-1.41L12 15.17V3h0zm-7 16h14v2H5z"/></svg><span>Download</span>`;
    btn.addEventListener("click", onDownloadClick);

    // Insert as first child so it sits next to Like/Share.
    container.insertAdjacentElement("afterbegin", btn);
  }

  async function onDownloadClick(e) {
    e.preventDefault();
    e.stopPropagation();
    const url = currentUrl();
    try {
      await ext.storage.local.set({ pendingUrl: url });
      await ext.runtime.sendMessage({ type: "YT_URL_CLICKED", url });
    } catch {}
    toast("Link sent to YT Local Downloader — click the extension icon to download.");
  }

  function toast(msg) {
    let t = document.getElementById(TOAST_ID);
    if (!t) {
      t = document.createElement("div");
      t.id = TOAST_ID;
      document.documentElement.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove("show"), 3200);
  }

  // SPA navigation: YouTube fires yt-navigate-finish; also observe DOM for button strip.
  document.addEventListener("yt-navigate-finish", () => {
    setTimeout(ensureButton, 400);
    setTimeout(ensureButton, 1200);
  });
  const obs = new MutationObserver(() => ensureButton());
  obs.observe(document.documentElement, { childList: true, subtree: true });

  // Initial attempts (page scripts load late)
  [500, 1500, 3000].forEach((ms) => setTimeout(ensureButton, ms));
  ensureButton();
})();
