import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import sanitize_filename

from models import OUTPUT_DIR, RECOMMENDED_DIR, YT_PREFIX, SearchResult


def extract_artist(title: str) -> Optional[str]:
    """Returns the artist portion of a 'Artist - Title' formatted string, or None."""
    parts = title.split(" - ", 1)
    if len(parts) == 2:
        return parts[0].strip() or None
    return None


def move_to_artist_subdir(path: Path, base_dir: Path) -> Path:
    artist = extract_artist(path.stem)
    if not artist:
        return path
    target_dir = base_dir / artist
    target_dir.mkdir(parents=True, exist_ok=True)
    new_path = target_dir / path.name
    if new_path != path:
        path.rename(new_path)
    return new_path


def delete_song_file(path: Path):
    """Deletes a song from disk, plus its artist folder if that becomes empty."""
    path.unlink(missing_ok=True)
    parent = path.parent
    if parent not in (OUTPUT_DIR, RECOMMENDED_DIR) and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


def song_label(path: Path) -> str:
    return path.stem


def yt_id_from_url(url: str) -> str:
    """Video ID from a youtube.com/watch?v=<id> or youtu.be/<id> URL."""
    parsed = urlparse(url)
    v = parse_qs(parsed.query).get("v")
    return v[0] if v else parsed.path.rstrip("/").rsplit("/", 1)[-1]


def yt_filename_stem(title: str) -> str:
    """Filename stem yt-dlp produces for a video with the given title."""
    return sanitize_filename(title)


def find_local(title: str) -> Optional[Path]:
    """Returns the already downloaded file for a YouTube title, if any."""
    stem = yt_filename_stem(title)
    for r in scan_songs():
        if r.local_path.stem == stem:
            return r.local_path
    return None


def normalize_title(title: str) -> str:
    """Strips (Lyrics), [HD], (Official Video) etc. for comparison."""
    t = title.lower()
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def scan_songs() -> List[SearchResult]:
    if not OUTPUT_DIR.exists():
        return []
    exts = {"*.mp3", "*.webm", "*.m4a", "*.opus"}
    paths = sorted(p for ext in exts for p in OUTPUT_DIR.rglob(ext))
    return [SearchResult(display=song_label(p), local_path=p) for p in paths]


def yt_video_id(query: str) -> Optional[str]:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = (info or {}).get("entries", [])
        if entries:
            return entries[0].get("id") or None
    except Exception:
        pass
    return None


def yt_radio(video_id: str, n: int = 30) -> List[SearchResult]:
    url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": n}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        results = []
        for entry in (info or {}).get("entries", []):
            title = entry.get("title") or "?"
            vid_id = entry.get("id") or ""
            if not vid_id:
                continue
            entry_url = f"https://www.youtube.com/watch?v={vid_id}"
            views = entry.get("view_count") or 0
            results.append(SearchResult(display=f"{YT_PREFIX}{title}", yt_url=entry_url, view_count=views))

        seen: dict[str, SearchResult] = {}
        for r in results:
            key = normalize_title(r.display)
            if key not in seen or r.view_count > seen[key].view_count:
                seen[key] = r
        return list(seen.values())
    except Exception:
        return []


def yt_search(query: str, n: int = 25) -> List[SearchResult]:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
        raw: List[SearchResult] = []
        for entry in (info or {}).get("entries", []):
            title = entry.get("title") or "?"
            url   = entry.get("url") or entry.get("webpage_url") or ""
            views = entry.get("view_count") or 0
            if not url:
                continue
            raw.append(SearchResult(
                display=f"{YT_PREFIX}{title}",
                yt_url=url,
                view_count=views,
            ))

        # Deduplication — for the same normalized title keep the one with more views
        seen: dict[str, SearchResult] = {}
        for r in raw:
            key = normalize_title(r.display)
            if key not in seen or r.view_count > seen[key].view_count:
                seen[key] = r

        return list(seen.values())
    except Exception:
        return []
