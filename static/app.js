/* ═══════════════════════════════════════════════════════════════════════════
   YouTube Downloader — Frontend (FastAPI + streaming progress)
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  "use strict";

  /* ── State ──────────────────────────────────────────────────────────────── */
  let format       = "mp4";
  let quality      = "best";
  let videoInfo    = null;
  let downloading  = false;
  let noPlaylist   = true;
  /* ── DOM refs ───────────────────────────────────────────────────────────── */
  const $ = (s) => document.querySelector(s);

  const apiKeyInput    = $("#apiKeyInput");
  const urlInput       = $("#urlInput");
  const pasteBtn       = $("#pasteBtn");
  const infoBtn        = $("#infoBtn");
  const previewCard    = $("#previewCard");
  const infoLoader     = $("#infoLoader");
  const formatChips    = $("#formatChips");
  const downloadBtn    = $("#downloadBtn");
  const dlBtnText      = $("#dlBtnText");
  const progressCard   = $("#progressCard");
  const progressFill   = $("#progressFill");
  const progressPct    = $("#progressPct");
  const progressSize   = $("#progressSize");
  const progressStatus = $("#progressStatus");
  const themeToggle    = $("#themeToggle");
  const toasts         = $("#toasts");
  const playlistToggle = $("#playlistToggle");
  const playlistChips  = $("#playlistChips");
  const playlistLabel  = $("#playlistLabel");
  const qualityChips   = $("#qualityChips");
  const qualityGroup   = $("#qualityGroup");
  const filenameGroup  = $("#filenameGroup");
  const filenameInput  = $("#filenameInput");
  const filenameExt    = $("#filenameExt");
  const versionBadge   = $("#versionBadge");
  const footerVersion  = $("#footerVersion");

  /* ── Init ───────────────────────────────────────────────────────────────── */
  function init() {
    const savedKey = localStorage.getItem("apiKey");
    if (savedKey) apiKeyInput.value = savedKey;
    bindEvents();
    fetchVersion();
  }

  async function fetchVersion() {
    try {
      const r = await fetch("/api/version");
      const data = await r.json();
      const v = `v${data.version}`;
      if (versionBadge) versionBadge.textContent = v;
      if (footerVersion) footerVersion.textContent = v;
    } catch { /* ignore */ }
  }

  function getKey() {
    const key = apiKeyInput.value.trim();
    if (key) localStorage.setItem("apiKey", key);
    return key;
  }

  function bindEvents() {
    pasteBtn.addEventListener("click", pasteAndFetch);
    infoBtn.addEventListener("click", () => fetchInfo());
    urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") fetchInfo(); });
    downloadBtn.addEventListener("click", startDownload);
    themeToggle.addEventListener("click", toggleTheme);

    formatChips.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (chip) setFormat(chip.dataset.value);
    });

    playlistChips.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      noPlaylist = chip.dataset.value === "video";
      playlistChips.querySelectorAll(".chip").forEach((c) => {
        const active = c.dataset.value === chip.dataset.value;
        c.classList.toggle("chip--active", active);
        c.setAttribute("aria-checked", active);
      });
    });

    qualityChips.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      quality = chip.dataset.value;
      qualityChips.querySelectorAll(".chip").forEach((c) => {
        const active = c.dataset.value === quality;
        c.classList.toggle("chip--active", active);
        c.setAttribute("aria-checked", active);
      });
    });
  }

  /* ── Paste & fetch ──────────────────────────────────────────────────────── */
  async function pasteAndFetch() {
    try {
      const text = await navigator.clipboard.readText();
      urlInput.value = text.trim();
    } catch {
      toast("No se pudo acceder al portapapeles", "error");
      return;
    }
    fetchInfo();
  }

  /* ── Fetch video info (GET) ─────────────────────────────────────────────── */
  async function fetchInfo() {
    const url = urlInput.value.trim();
    const key = getKey();
    if (!key) { toast("Ingresa tu API Key", "error"); return; }
    if (!url) { toast("Ingresa una URL", "error"); return; }

    previewCard.hidden = true;
    infoLoader.hidden  = false;
    infoBtn.disabled   = true;

    try {
      const params = new URLSearchParams({ url, key });
      const r = await fetch(`/api/info?${params}`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Error desconocido");

      videoInfo = data;
      showPreview(data);
    } catch (err) {
      const msg = err.message;
      toast(msg, "error");
      // Show extra help for cookie-related errors
      if (msg.includes("cookie") || msg.includes("Cookie") || msg.includes("bot") || msg.includes("403")) {
        setTimeout(() => toast("💡 Ve a tu panel de Render/Railway → Variables → añade YT_COOKIES con el contenido de cookies.txt exportado desde tu navegador", "info"), 500);
      }
    } finally {
      infoLoader.hidden = true;
      infoBtn.disabled  = false;
    }
  }

  function showPreview(info) {
    $("#previewTitle").textContent   = info.title;
    $("#previewChannel").textContent = info.channel;
    const thumb = $("#previewThumb");
    if (info.thumbnail) {
      thumb.src = info.thumbnail;
      thumb.hidden = false;
    }
    $("#previewDuration").textContent = info.duration_str || "";

    const metaParts = [];
    if (info.duration_str && info.duration_str !== "0:00") metaParts.push(info.duration_str);
    if (info.is_playlist) metaParts.push(`Playlist: ${info.playlist_count} videos`);
    $("#previewMeta").textContent = metaParts.join("  ·  ");

    // Show/hide playlist toggle
    if (info.is_playlist) {
      playlistLabel.textContent = `"${info.playlist_title || "Playlist"}" — ${info.playlist_count} videos`;
      playlistToggle.hidden = false;
      // Reset to "solo este video" by default
      noPlaylist = true;
      playlistChips.querySelectorAll(".chip").forEach((c) => {
        const active = c.dataset.value === "video";
        c.classList.toggle("chip--active", active);
        c.setAttribute("aria-checked", active);
      });
    } else {
      playlistToggle.hidden = true;
      noPlaylist = true;
    }

    previewCard.hidden = false;
    previewCard.classList.remove("anim-entry");
    void previewCard.offsetWidth;
    previewCard.classList.add("anim-entry");

    // Show filename input pre-filled with video title
    filenameInput.value = info.title || "";
    filenameExt.textContent = `.${format}`;
    filenameGroup.hidden = false;
  }

  /* ── Format chips ───────────────────────────────────────────────────────── */
  function setFormat(f) {
    format = f;
    formatChips.querySelectorAll(".chip").forEach((c) => {
      const active = c.dataset.value === f;
      c.classList.toggle("chip--active", active);
      c.setAttribute("aria-checked", active);
    });
    filenameExt.textContent = `.${f}`;
    qualityGroup.style.display = f === "mp3" ? "none" : "";
  }

  /* ── Helpers ────────────────────────────────────────────────────────────── */
  function fmtBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  /* ── Download with progress ─────────────────────────────────────────────── */
  async function startDownload() {
    if (downloading) return;
    const url = urlInput.value.trim();
    const key = getKey();
    if (!key) { toast("Ingresa tu API Key", "error"); return; }
    if (!url) { toast("Ingresa una URL", "error"); return; }

    downloading = true;
    downloadBtn.disabled = true;
    dlBtnText.textContent = "Preparando…";

    // Show progress card in "preparing" state
    progressCard.hidden = false;
    progressFill.style.width = "0%";
    progressPct.textContent = "—";
    progressSize.textContent = "—";
    progressStatus.textContent = "Preparando descarga… puede tardar unos segundos";
    progressFill.classList.add("progress-fill--indeterminate");

    try {
      const customName = filenameInput ? filenameInput.value.trim() : "";
      const params = new URLSearchParams({ url, format, quality, no_playlist: noPlaylist, custom_name: customName, key });
      const response = await fetch(`/api/download?${params}`);

      if (!response.ok) {
        let errMsg = "Error al descargar";
        try {
          const errData = await response.json();
          errMsg = errData.detail || errMsg;
        } catch { /* not JSON */ }
        throw new Error(errMsg);
      }

      // Get filename from Content-Disposition header
      const disposition = response.headers.get("Content-Disposition") || "";
      const filenameMatch = disposition.match(/filename="?([^";\n]+)"?/);
      const filename = filenameMatch ? filenameMatch[1] : `download.${format}`;

      // Get total size for progress
      const contentLength = parseInt(response.headers.get("Content-Length") || "0", 10);

      // Switch to download progress mode
      progressFill.classList.remove("progress-fill--indeterminate");
      progressStatus.textContent = `Descargando: ${filename}`;
      dlBtnText.textContent = "Descargando…";

      // Stream the response and track progress
      const reader = response.body.getReader();
      const chunks = [];
      let received = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        chunks.push(value);
        received += value.length;

        if (contentLength > 0) {
          const pct = Math.min(100, (received / contentLength) * 100);
          progressFill.style.width = `${pct.toFixed(1)}%`;
          progressPct.textContent = `${pct.toFixed(1)} %`;
        }
        progressSize.textContent = `${fmtBytes(received)}${contentLength ? ` / ${fmtBytes(contentLength)}` : ""}`;
      }

      // Build blob and trigger download
      const blob = new Blob(chunks);
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);

      // Done!
      progressFill.style.width = "100%";
      progressPct.textContent = "100 %";
      progressStatus.textContent = `Completado: ${filename}`;
      toast(`Descarga completada: ${filename}`, "success");

    } catch (err) {
      const msg = err.message;
      toast(msg, "error");
      if (msg.includes("cookie") || msg.includes("Cookie") || msg.includes("bot") || msg.includes("403")) {
        setTimeout(() => toast("💡 Configura YT_COOKIES en las Variables del servicio para resolver este error", "info"), 500);
      }
      progressStatus.textContent = `Error: ${msg}`;
      progressFill.classList.remove("progress-fill--indeterminate");
    } finally {
      downloading = false;
      downloadBtn.disabled = false;
      dlBtnText.textContent = "\u2B07 DESCARGAR";
    }
  }

  /* ── Theme ──────────────────────────────────────────────────────────────── */
  function toggleTheme() {
    const html = document.documentElement;
    const next = html.dataset.theme === "dark" ? "light" : "dark";
    html.dataset.theme = next;
    localStorage.setItem("theme", next);
    const icon = $("#themeIcon path");
    if (next === "light") {
      icon.setAttribute("d", "M12 3v1m0 16v1m8.66-13.66l-.71.71M4.05 19.95l-.71.71M21 12h1M2 12H1m16.66 7.66l-.71-.71M4.05 4.05l-.71-.71M16 12a4 4 0 11-8 0 4 4 0 018 0z");
    } else {
      icon.setAttribute("d", "M21 12.79A9 9 0 1111.21 3a7 7 0 009.79 9.79z");
    }
  }

  const saved = localStorage.getItem("theme");
  if (saved) document.documentElement.dataset.theme = saved;

  /* ── Toast notifications ────────────────────────────────────────────────── */
  function toast(msg, type = "info") {
    const el = document.createElement("div");
    el.className = `toast toast--${type}`;
    el.textContent = msg;
    toasts.appendChild(el);
    setTimeout(() => {
      el.classList.add("toast--out");
      el.addEventListener("animationend", () => el.remove());
    }, 4500);
  }

  /* ── Boot ───────────────────────────────────────────────────────────────── */
  init();
})();
