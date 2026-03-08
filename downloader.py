"""YouTube download engine powered by yt-dlp."""

import os
import shutil
import threading
from pathlib import Path

import yt_dlp

# ── Quality maps ─────────────────────────────────────────────────────────────

VIDEO_QUALITY: dict[str, str] = {
    "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    "1080p": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
    "720p":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
    "480p":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
    "360p":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
}

AUDIO_QUALITY: dict[str, str] = {
    "320kbps": "320",
    "192kbps": "192",
    "128kbps": "128",
}

_FALLBACK = "best[ext=mp4]/best"


# ── FFmpeg discovery ─────────────────────────────────────────────────────────

def _find_ffmpeg() -> str | None:
    """Return path to a *directory* containing ``ffmpeg(.exe)``."""
    if exe := shutil.which("ffmpeg"):
        return str(Path(exe).parent)
    try:
        import imageio_ffmpeg
        source = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    ffmpeg_dir = Path(__file__).parent / "_ffmpeg"
    ffmpeg_dir.mkdir(exist_ok=True)
    target = ffmpeg_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not target.exists():
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    return str(ffmpeg_dir)


# ── Formatting helpers ───────────────────────────────────────────────────────

def _fmt_speed(bps: float) -> str:
    if bps <= 0:
        return "—"
    for u in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.1f} {u}"
        bps /= 1024
    return f"{bps:.1f} TB/s"


def _fmt_eta(s: int) -> str:
    if not s or s <= 0:
        return "—"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def fmt_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── Downloader ───────────────────────────────────────────────────────────────

class Downloader:
    """Thread-safe video/audio downloader with progress callbacks."""

    def __init__(self, on_progress=None, on_status=None, on_finish=None):
        self.on_progress = on_progress
        self.on_status   = on_status
        self.on_finish   = on_finish
        self.is_downloading = False
        self._cancel        = False
        self.ffmpeg_location = _find_ffmpeg()
        self._playlist_total = 0
        self._playlist_done  = 0

    @property
    def has_ffmpeg(self) -> bool:
        return self.ffmpeg_location is not None

    # ── public ───────────────────────────────────────────────────────────

    def get_info(self, url: str) -> dict | None:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": "in_playlist",
                                    "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
            is_pl = "entries" in info
            return {
                "title":       info.get("title", "—"),
                "channel":     info.get("channel") or info.get("uploader", "—"),
                "duration":    info.get("duration") or 0,
                "duration_str": fmt_duration(info.get("duration") or 0),
                "thumbnail":   info.get("thumbnail", ""),
                "is_playlist": is_pl,
                "playlist_count": len(list(info.get("entries") or [])) if is_pl else 0,
            }
        except Exception:
            return None

    def download(self, url: str, fmt: str, quality: str, output: str,
                 no_playlist: bool = False):
        if self.is_downloading:
            return
        self._cancel        = False
        self.is_downloading = True
        self._playlist_total = 0
        self._playlist_done  = 0

        def _run():
            title = "video"
            try:
                self._emit_status("Obteniendo información del video…")
                with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": "in_playlist",
                                        "skip_download": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                is_pl = "entries" in info and not no_playlist
                title  = info.get("title", "video")
                if is_pl:
                    self._playlist_total = len(list(info.get("entries") or []))
                    self._emit_status(f"Playlist: {title} — {self._playlist_total} videos")
                else:
                    self._emit_status(f"Descargando: {title}")
                opts = self._build_opts(fmt, quality, output, playlist_mode=is_pl)
                if no_playlist:
                    opts["noplaylist"] = True
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                if not self._cancel and self.on_finish:
                    self.on_finish(True, title)
            except yt_dlp.utils.DownloadCancelled:
                if self.on_finish:
                    self.on_finish(False, "Cancelado por el usuario")
            except Exception as exc:
                if self.on_finish:
                    self.on_finish(False, str(exc))
            finally:
                self.is_downloading = False

        threading.Thread(target=_run, daemon=True).start()

    def cancel(self):
        self._cancel = True

    # ── private ──────────────────────────────────────────────────────────

    def _emit_status(self, msg, error=False):
        if self.on_status:
            self.on_status(msg, error)

    def _progress_hook(self, d: dict):
        if self._cancel:
            raise yt_dlp.utils.DownloadCancelled()
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            down  = d.get("downloaded_bytes", 0)
            pct   = down / total * 100 if total else 0
            if self.on_progress:
                self.on_progress(pct, _fmt_speed(d.get("speed") or 0),
                                 _fmt_eta(d.get("eta") or 0))
        elif st == "finished":
            self._playlist_done += 1
            name = Path(d.get("filename", "")).name
            suf  = f"  ({self._playlist_done}/{self._playlist_total})" if self._playlist_total > 1 else ""
            self._emit_status(f"Procesando: {name}{suf}")

    def _build_opts(self, fmt: str, quality: str, output: str,
                    playlist_mode: bool = False) -> dict:
        tpl = "%(playlist_index)s - %(title)s.%(ext)s" if playlist_mode else "%(title)s.%(ext)s"
        opts: dict = {
            "outtmpl":         str(Path(output) / tpl),
            "progress_hooks":  [self._progress_hook],
            "quiet":           True,
            "no_warnings":     True,
            "retries":         5,
            "fragment_retries": 5,
            "restrictfilenames": True,
        }
        if self.ffmpeg_location:
            opts["ffmpeg_location"] = self.ffmpeg_location

        if fmt.upper() == "MP4":
            fs = VIDEO_QUALITY.get(quality, VIDEO_QUALITY["best"])
            if self.has_ffmpeg:
                opts["format"] = fs
                opts["merge_output_format"] = "mp4"
            else:
                opts["format"] = _FALLBACK
                self._emit_status("Sin ffmpeg — calidad limitada")
        else:
            if not self.has_ffmpeg:
                raise RuntimeError("FFmpeg necesario para MP3. Instala: pip install imageio-ffmpeg")
            br = AUDIO_QUALITY.get(quality, "192")
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": br,
            }]
        return opts
