"""YouTube Downloader — FastAPI backend for Railway deployment.

Streams video/audio directly to the browser via yt-dlp (no temp files on disk).
Protected by API_KEY env variable.  Rate-limited to 5 req/min per IP.
"""

import asyncio
import os
import re
import shutil
import sys
import time
from collections import defaultdict
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
    # prune old entries
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


_SAFE_RE = re.compile(r'[^A-Za-z0-9._-]')


def _safe_filename(name: str, ext: str) -> str:
    clean = _SAFE_RE.sub("_", name)[:120]
    return f"{clean}.{ext}"


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
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True,
                                "extract_flat": "in_playlist"}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.get_event_loop().run_in_executor(None, extract)
    except Exception:
        raise HTTPException(400, "Could not retrieve video info — check the URL")

    is_pl = "entries" in info
    formats_raw = info.get("formats") or []

    # Build a simplified list of available formats
    available = []
    seen = set()
    for f in formats_raw:
        label = f.get("format_note") or f.get("format") or ""
        ext = f.get("ext", "")
        h = f.get("height")
        abr = f.get("abr")
        entry_key = f"{label}-{ext}"
        if entry_key in seen:
            continue
        seen.add(entry_key)
        available.append({
            "format_id": f.get("format_id", ""),
            "ext": ext,
            "resolution": f"{h}p" if h else None,
            "abr": f"{abr}kbps" if abr else None,
            "note": label,
        })

    return {
        "title": info.get("title", "—"),
        "channel": info.get("channel") or info.get("uploader", "—"),
        "duration": info.get("duration") or 0,
        "duration_str": _fmt_duration(info.get("duration")),
        "thumbnail": info.get("thumbnail", ""),
        "is_playlist": is_pl,
        "playlist_count": len(list(info.get("entries") or [])) if is_pl else 0,
        "formats": available,
    }


# ── GET /api/download ───────────────────────────────────────────────────────

@app.get("/api/download")
async def api_download(
    url: str = Query(..., min_length=1),
    format: str = Query("mp4", pattern="^(mp4|mp3)$"),
    key: str = Query(...),
    request: Request = None,
):
    _check_key(key)
    _check_rate(request.client.host)

    # Fetch title for Content-Disposition
    def get_title():
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "download")

    try:
        title = await asyncio.get_event_loop().run_in_executor(None, get_title)
    except Exception:
        title = "download"

    is_audio = format == "mp3"
    filename = _safe_filename(title or "download", "mp3" if is_audio else "mp4")
    media_type = "audio/mpeg" if is_audio else "video/mp4"

    async def stream_response() -> AsyncGenerator[bytes, None]:
        ytdlp_bin = shutil.which("yt-dlp")
        cmd = [ytdlp_bin] if ytdlp_bin else [sys.executable, "-m", "yt_dlp"]

        cmd += ["--quiet", "--no-warnings", "--no-playlist",
                "--retries", "3", "-o", "-"]

        if is_audio:
            cmd += ["--extract-audio", "--audio-format", "mp3",
                    "--audio-quality", "192K"]
        else:
            cmd += [
                "-f",
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo+bestaudio/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
            ]
        cmd.append(url)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(64 * 1024)
            if not chunk:
                break
            yield chunk

        await proc.wait()

    return StreamingResponse(
        stream_response(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
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
