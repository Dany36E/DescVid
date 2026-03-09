"""YouTube Downloader — FastAPI backend for Railway/Render deployment.

Downloads via yt-dlp to a temp file, streams to browser, then cleans up.
Protected by API_KEY env variable.  Rate-limited to 5 req/min per IP.
"""

import asyncio
import glob
import logging
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import AsyncGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("descvid")

import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Config ───────────────────────────────────────────────────────────────────

APP_VERSION = "1.4.5"
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

# ── Auth support (YT_COOKIES or YT_OAUTH2_TOKEN env vars) ───────────────────

_cookies_file: str | None = None
_oauth2_configured: bool = False


@app.on_event("startup")
async def _on_startup():
    global _cookies_file, _oauth2_configured

    raw_cookies = os.environ.get("YT_COOKIES", "").strip()
    if raw_cookies:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="yt_cookies_")
        with os.fdopen(fd, "w") as f:
            f.write(raw_cookies)
        _cookies_file = path
        logger.info("[startup] YT_COOKIES loaded: %d bytes → %s", len(raw_cookies), path)
        # Verify the file is readable
        try:
            size = os.path.getsize(path)
            logger.info("[startup] Cookie file written OK: %d bytes on disk", size)
        except Exception as e:
            logger.error("[startup] Cookie file error: %s", e)
    else:
        logger.warning("[startup] YT_COOKIES not set — bot detection bypass only")

    raw_oauth2 = os.environ.get("YT_OAUTH2_TOKEN", "").strip()
    if raw_oauth2:
        import json as _json
        try:
            _json.loads(raw_oauth2)
            cache_dir = Path.home() / ".cache" / "yt-dlp"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "youtube_oauth2_token.json").write_text(raw_oauth2)
            _oauth2_configured = True
            logger.info("[startup] YT_OAUTH2_TOKEN loaded OK")
        except Exception as e:
            logger.error("[startup] YT_OAUTH2_TOKEN parse error: %s", e)


def _base_ydl_opts() -> dict:
    """Common yt-dlp options: auth, headers, retries, client bypass."""
    has_cookies = bool(_cookies_file and os.path.isfile(_cookies_file))

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 10,
        "http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
        },
        "sleep_interval_requests": 1,
    }

    if has_cookies:
        # web_embedded + web both accept cookiefile.
        # web_embedded has looser bot detection rules than plain web.
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["web_embedded", "web"],
            }
        }
        opts["cookiefile"] = _cookies_file
    else:
        # No cookies: use android + tv_embedded which bypass bot checks
        # better than 'web' on datacenter IPs.
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["android", "tv_embedded", "web_creator"],
                "player_skip": ["webpage"],
            }
        }

    return opts


# ── Error messages ───────────────────────────────────────────────────────────

_ERROR_MAP = [
    ("Sign in to confirm", "YouTube detectó el servidor como bot. Solución: agrega YT_OAUTH2_TOKEN o YT_COOKIES en las Variables de entorno de tu servicio en Render."),
    ("Please sign in", "YouTube detectó el servidor como bot. Solución: agrega YT_OAUTH2_TOKEN o YT_COOKIES en las Variables de entorno de tu servicio en Render."),
    ("Video unavailable", "El video no está disponible. Puede ser privado o eliminado."),
    ("is not a valid URL", "La URL no es válida. Verifica e intenta de nuevo."),
    ("Geo-restricted", "Este video no está disponible en tu región."),
    ("age-restricted", "Video restringido por edad. Necesitas cookies de una cuenta con edad verificada."),
    ("Private video", "Este video es privado."),
    ("has been removed", "Este video ha sido eliminado."),
    ("copyright", "Video bloqueado por derechos de autor."),
    ("HTTP Error 403", "Acceso denegado (403). Configura YT_COOKIES en Variables del servicio."),
    ("HTTP Error 429", "Demasiadas peticiones a YouTube. Espera unos minutos e intenta de nuevo."),
    ("Incomplete data", "YouTube envió datos incompletos. Intenta de nuevo en unos segundos."),
    ("Unable to extract", "No se pudo extraer información. Intenta de nuevo o usa otra URL."),
    ("timed out", "La conexión tardó demasiado. Intenta de nuevo."),
]


def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    for pattern, friendly in _ERROR_MAP:
        if pattern.lower() in msg.lower():
            return friendly
    return f"Error: {msg[:200]}"


# ── Rate limiter (5 req/min per IP, in-memory) ──────────────────────────────

_rate: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 15
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


# ── GET /api/version ─────────────────────────────────────────────────────────

@app.get("/api/version")
async def api_version():
    return {"version": APP_VERSION}


# ── GET /api/debug (diagnóstico — protegido por API key) ─────────────────────

@app.get("/api/debug")
async def api_debug(key: str = Query(...)):
    _check_key(key)
    cookies_ok = bool(_cookies_file and os.path.isfile(_cookies_file))
    cookies_size = os.path.getsize(_cookies_file) if cookies_ok else 0
    env_cookies_len = len(os.environ.get("YT_COOKIES", ""))
    return {
        "version": APP_VERSION,
        "cookies_file_set": _cookies_file is not None,
        "cookies_file_exists": cookies_ok,
        "cookies_file_bytes": cookies_size,
        "env_YT_COOKIES_length": env_cookies_len,
        "oauth2_configured": _oauth2_configured,
    }


# ── GET /api/info ────────────────────────────────────────────────────────────

@app.get("/api/info")
async def api_info(
    url: str = Query(..., min_length=1),
    key: str = Query(...),
    request: Request = None,
):
    _check_key(key)
    _check_rate(request.client.host)

    # Detect playlist URLs before extraction
    is_playlist_url = "list=" in url

    def extract_video():
        """Full extraction of single video — gets duration, thumbnail, etc."""
        opts = _base_ydl_opts()
        opts.update({"skip_download": True, "noplaylist": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    def extract_playlist():
        """Flat extraction to count playlist items quickly."""
        opts = _base_ydl_opts()
        opts.update({"skip_download": True, "extract_flat": "in_playlist"})
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    # Always get full video info first (provides duration, quality info, etc.)
    try:
        video_info = await asyncio.get_event_loop().run_in_executor(None, extract_video)
    except Exception as exc:
        raise HTTPException(400, _friendly_error(exc))

    # If URL looks like a playlist, also get playlist metadata
    is_pl = False
    playlist_count = 0
    playlist_title = None

    if is_playlist_url:
        try:
            pl_info = await asyncio.get_event_loop().run_in_executor(None, extract_playlist)
            if "entries" in pl_info:
                is_pl = True
                playlist_count = len(list(pl_info.get("entries") or []))
                playlist_title = pl_info.get("title", "—")
        except Exception:
            pass  # playlist detection failed — show single video only

    return {
        "title": video_info.get("title", "—"),
        "channel": video_info.get("channel") or video_info.get("uploader", "—"),
        "duration": video_info.get("duration") or 0,
        "duration_str": _fmt_duration(video_info.get("duration")),
        "thumbnail": video_info.get("thumbnail", ""),
        "is_playlist": is_pl,
        "playlist_count": playlist_count,
        "playlist_title": playlist_title,
    }


# ── GET /api/download ───────────────────────────────────────────────────────

@app.get("/api/download")
async def api_download(
    url: str = Query(..., min_length=1),
    format: str = Query("mp4", pattern="^(mp4|mp3)$"),
    quality: str = Query("best", pattern="^(best|720|480)$"),
    no_playlist: bool = Query(True),
    custom_name: str = Query(""),
    key: str = Query(...),
    request: Request = None,
):
    _check_key(key)
    _check_rate(request.client.host)

    is_audio = format == "mp3"
    tmp_dir = tempfile.mkdtemp(prefix="ytdl_")

    def run_download() -> tuple[str, str]:
        outtmpl = os.path.join(tmp_dir, "%(title)s.%(ext)s")
        opts = _base_ydl_opts()
        opts.update({
            "outtmpl": outtmpl,
            "noplaylist": no_playlist,
            "restrictfilenames": False,
        })

        if is_audio:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            quality_map = {
                "best": "bestvideo+bestaudio/best",
                "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "480": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
            }
            opts["format"] = quality_map.get(quality, quality_map["best"])
            opts["merge_output_format"] = "mp4"
            opts["format_sort"] = ["ext:mp4:m4a", "res", "codec:h264"]

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "download")

        files = glob.glob(os.path.join(tmp_dir, "*"))
        if not files:
            raise RuntimeError("No se generó ningún archivo")
        return files[0], title

    try:
        filepath, title = await asyncio.get_event_loop().run_in_executor(
            None, run_download
        )
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(500, _friendly_error(exc))

    actual_ext = Path(filepath).suffix.lstrip(".")
    file_size = os.path.getsize(filepath)
    name = custom_name.strip() if custom_name.strip() else title
    filename = _safe_filename(name, actual_ext)
    media_type = "audio/mpeg" if is_audio else "video/mp4"

    async def stream_and_cleanup() -> AsyncGenerator[bytes, None]:
        try:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(256 * 1024)
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
