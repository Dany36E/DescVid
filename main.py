"""YouTube Downloader — FastAPI backend for Railway/Render deployment.

Downloads via yt-dlp to a temp file, streams to browser, then cleans up.
Protected by API_KEY env variable.  Rate-limited to 5 req/min per IP.
"""

import asyncio
import glob
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import AsyncGenerator

import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Config ───────────────────────────────────────────────────────────────────

API_KEY = os.environ.get("API_KEY", "changeme")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

app = FastAPI(title="YouTube Downloader")

# ── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Rate limiter (5 req/min per IP, in-memory) ──────────────────────────────

_rate: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 5
RATE_WINDOW = 60  # seconds


def _check_rate(ip: str):
    now = time.time()
    hits = _rate[ip]
    _rate[ip] = [t for t in hits if now - t < RATE_WINDOW]
    if len(_rate[ip]) >= RATE_LIMIT:
        raise HTTPException(429, "Rate limit exceeded — max 5 requests per minute")
    _rate[ip].append(now)


# ── Auth helper ──────────────────────────────────────────────────────────────

def _check_key(key: str | None):
    if not key or key != API_KEY:
        raise HTTPException(403, "Invalid or missing API key")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "0:00"
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_SAFE_RE = re.compile(r'[^A-Za-z0-9._\- ]')


def _safe_filename(name: str, ext: str) -> str:
    clean = _SAFE_RE.sub("_", name).strip("_")[:120]
    return f"{clean}.{ext}" if clean else f"download.{ext}"


# ── GET /api/info ────────────────────────────────────────────────────────────

@app.get("/api/info")
async def api_info(
    url: str = Query(..., min_length=1),
    key: str = Query(...),
    request: Request = None,
):
    _check_key(key)
    _check_rate(request.client.host)

    def extract():
        # First pass: flat extract to detect playlist quickly
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True,
                                "extract_flat": "in_playlist"}) as ydl:
            return ydl.extract_info(url, download=False)

    def extract_video():
        # Full extract of the single video (no playlist)
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True,
                                "noplaylist": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.get_event_loop().run_in_executor(None, extract)
    except Exception:
        raise HTTPException(400, "Could not retrieve video info — check the URL")

    is_pl = "entries" in info
    playlist_count = len(list(info.get("entries") or [])) if is_pl else 0
    playlist_title = info.get("title", "—") if is_pl else None

    # If it's a playlist URL, also fetch the individual video info
    if is_pl:
        try:
            video_info = await asyncio.get_event_loop().run_in_executor(None, extract_video)
        except Exception:
            video_info = None
    else:
        video_info = info

    # Use video-level info for display, fall back to playlist info
    display = video_info if video_info else info

    return {
        "title": display.get("title", "—"),
        "channel": display.get("channel") or display.get("uploader", "—"),
        "duration": display.get("duration") or 0,
        "duration_str": _fmt_duration(display.get("duration")),
        "thumbnail": display.get("thumbnail", ""),
        "is_playlist": is_pl,
        "playlist_count": playlist_count,
        "playlist_title": playlist_title,
    }


# ── GET /api/download ───────────────────────────────────────────────────────

@app.get("/api/download")
async def api_download(
    url: str = Query(..., min_length=1),
    format: str = Query("mp4", pattern="^(mp4|mp3)$"),
    no_playlist: bool = Query(True),
    key: str = Query(...),
    request: Request = None,
):
    _check_key(key)
    _check_rate(request.client.host)

    is_audio = format == "mp3"
    tmp_dir = tempfile.mkdtemp(prefix="ytdl_")

    def run_download() -> tuple[str, str]:
        """Download to temp dir with yt-dlp, return (filepath, title)."""
        outtmpl = os.path.join(tmp_dir, "%(title)s.%(ext)s")
        opts: dict = {
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": no_playlist,
            "retries": 5,
            "restrictfilenames": False,
        }

        if is_audio:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            opts["format"] = (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo+bestaudio/best[ext=mp4]/best"
            )
            opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "download")

        # Find the downloaded file (yt-dlp may change ext after postprocessing)
        files = glob.glob(os.path.join(tmp_dir, "*"))
        if not files:
            raise RuntimeError("Download failed — no file produced")
        filepath = files[0]
        return filepath, title

    try:
        filepath, title = await asyncio.get_event_loop().run_in_executor(
            None, run_download
        )
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(500, f"Download failed: {exc}")

    actual_ext = Path(filepath).suffix.lstrip(".")
    file_size = os.path.getsize(filepath)
    filename = _safe_filename(title, actual_ext)
    media_type = "audio/mpeg" if is_audio else "video/mp4"

    async def stream_and_cleanup() -> AsyncGenerator[bytes, None]:
        try:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(256 * 1024)  # 256KB chunks
                    if not chunk:
                        break
                    yield chunk
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(
        stream_and_cleanup(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(file_size),
            "Cache-Control": "no-store",
        },
    )


# ── Serve frontend ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
