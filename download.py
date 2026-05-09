from pathlib import Path
from typing import Callable

from models import OUTPUT_DIR, RECOMMENDED_DIR

_NOT_MUSIC_KEYWORDS = [
    "podcast", "interview", "intervju", "news", "vijesti", "vesti",
    "documentary", "dokumentarac", "lecture", "predavanje", "tutorial",
    "unboxing", "review", "recenzija", "vlog", "gameplay", "playthrough",
    "highlights", "compilation", "funny moments", "react", "reaction",
    "talk show", "stand up", "comedy show", "trailer", "teaser",
]


def _music_filter(info: dict, *, incomplete: bool):
    """Returns a skip message or None (download)."""
    duration = info.get("duration")
    if duration is not None:
        if duration < 90:
            return "Too short (< 90s)"
        if duration > 900:
            return "Too long (> 15min)"

    title = (info.get("title") or "").lower()
    for kw in _NOT_MUSIC_KEYWORDS:
        if kw in title:
            return f"Not music ('{kw}' in title)"

    return None


def make_ydl_opts(
    progress_hook: Callable,
    single: bool = False,
    music_only: bool = False,
    recommended: bool = False,
) -> dict:
    out_dir = RECOMMENDED_DIR if recommended else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "noplaylist": single,
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
        "keepvideo": False,
        "download_archive": str(out_dir / ".archive"),
        "nooverwrites": True,
        "progress_hooks": [progress_hook],
    }
    if music_only:
        opts["match_filter"] = _music_filter
    return opts
