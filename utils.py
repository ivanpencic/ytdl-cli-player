import re
from pathlib import Path
from typing import List, Optional

import yt_dlp

from models import OUTPUT_DIR, SearchResult


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


def song_label(path: Path) -> str:
    return path.stem


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
            results.append(SearchResult(display=f"[YT]  {title}", yt_url=entry_url, view_count=views))

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
                display=f"[YT]  {title}",
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
