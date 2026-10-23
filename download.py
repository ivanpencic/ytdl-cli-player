import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

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


_archive_lock = threading.Lock()


def archived_ids(out_dir: Path) -> set[str]:
    """Video IDs recorded in out_dir/.archive (lines look like 'youtube <id>')."""
    path = out_dir / ".archive"
    if not path.exists():
        return set()
    return {parts[-1] for line in path.read_text().splitlines() if (parts := line.split())}


def forget_archived(out_dir: Path, video_id: str) -> bool:
    """Removes video_id from out_dir/.archive so yt-dlp downloads it again. Returns True if removed."""
    path = out_dir / ".archive"
    with _archive_lock:
        if not path.exists():
            return False
        lines = path.read_text().splitlines()
        kept = [line for line in lines if line.split()[-1:] != [video_id]]
        if len(kept) == len(lines):
            return False
        path.write_text("".join(f"{line}\n" for line in kept))
        return True


class YdlErrorLog:
    """yt-dlp logger that keeps the last error instead of printing (prints would break the TUI)."""

    def __init__(self):
        self.last: Optional[str] = None

    def debug(self, msg: str):
        pass

    def info(self, msg: str):
        pass

    def warning(self, msg: str):
        pass

    def error(self, msg: str):
        self.last = msg.removeprefix("ERROR: ").strip()


def _js_runtimes() -> dict:
    """YouTube needs a JS runtime to solve its challenges; yt-dlp only enables deno by default."""
    runtimes: dict = {"deno": {}}
    node = shutil.which("node")
    if node:
        runtimes["node"] = {"path": node}
    return runtimes


def make_ydl_opts(
    progress_hook: Callable,
    single: bool = False,
    music_only: bool = False,
    recommended: bool = False,
    logger: Optional[YdlErrorLog] = None,
) -> dict:
    out_dir = RECOMMENDED_DIR if recommended else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "noplaylist": single,
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
        "keepvideo": False,
        "download_archive": str(out_dir / ".archive"),
        "nooverwrites": True,
        "progress_hooks": [progress_hook],
        "js_runtimes": _js_runtimes(),
    }
    if logger:
        opts["logger"] = logger
    if music_only:
        opts["match_filter"] = _music_filter
    return opts
