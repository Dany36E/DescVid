/* ═══════════════════════════════════════════════════════════════════════════
   YouTube Downloader — Frontend (FastAPI / Railway)
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  "use strict";

  /* ── State ──────────────────────────────────────────────────────────────── */
  let format    = "mp4";
  let videoInfo = null;

  /* ── DOM refs ───────────────────────────────────────────────────────────── */
  const $ = (s) => document.querySelector(s);

  const apiKeyInput   = $("#apiKeyInput");
  const urlInput      = $("#urlInput");
  const pasteBtn      = $("#pasteBtn");
  const infoBtn       = $("#infoBtn");
  const previewCard   = $("#previewCard");
  const infoLoader    = $("#infoLoader");
  const formatChips   = $("#formatChips");
  const downloadBtn   = $("#downloadBtn");
  const dlBtnText     = $("#dlBtnText");
  const themeToggle   = $("#themeToggle");
  const toasts        = $("#toasts");

  /* ── Init ───────────────────────────────────────────────────────────────── */
  function init() {
    // Restore saved API key
    const savedKey = localStorage.getItem("apiKey");
    if (savedKey) apiKeyInput.value = savedKey;

    bindEvents();
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
      toast(err.message, "error");
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
    if (info.duration_str) metaParts.push(info.duration_str);
    if (info.is_playlist) metaParts.push(`Playlist: ${info.playlist_count} videos`);
    $("#previewMeta").textContent = metaParts.join("  ·  ");

    previewCard.hidden = false;
    previewCard.classList.remove("anim-entry");
    void previewCard.offsetWidth;
    previewCard.classList.add("anim-entry");
  }

  /* ── Format chips ───────────────────────────────────────────────────────── */
  function setFormat(f) {
    format = f;
    formatChips.querySelectorAll(".chip").forEach((c) => {
      const active = c.dataset.value === f;
      c.classList.toggle("chip--active", active);
      c.setAttribute("aria-checked", active);
    });
  }

  /* ── Download (triggers browser download via GET) ───────────────────────── */
  function startDownload() {
    const url = urlInput.value.trim();
    const key = getKey();
    if (!key) { toast("Ingresa tu API Key", "error"); return; }
    if (!url) { toast("Ingresa una URL", "error"); return; }

    const params = new URLSearchParams({ url, format, key });
    // Open in a new hidden iframe so the browser handles the file download
    // without navigating away from the page
    const downloadUrl = `/api/download?${params}`;

    toast("Descarga iniciada — el archivo se descargará en tu navegador", "info");

    const a = document.createElement("a");
    a.href = downloadUrl;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
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

  // Restore saved theme
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
