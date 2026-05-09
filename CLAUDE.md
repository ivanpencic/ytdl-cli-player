# ytdl player — CLAUDE.md

> **IMPORTANT:** Whenever `player.py` is modified (new features, refactors, bug fixes, keybinding changes), update this file to reflect the current state of the codebase.

## Overview

Terminal-based YouTube audio player (TUI) built with [Textual](https://textual.textualize.io/). Downloads audio via `yt-dlp`, converts to MP3 using `ffmpeg`, and plays with `ffplay` (part of FFmpeg). All playback is offline after download.

**Entry point:** `start.sh` → `env/bin/python player.py`

---

## Dependencies

| Tool / Library | Role |
|---|---|
| `yt-dlp` | YouTube search and audio download |
| `ffmpeg` / `ffplay` | Audio conversion (M4A/WebM → MP3) and playback |
| `textual` | Terminal UI framework |

Python venv is at `env/`. Activate with `source env/bin/activate` or run via `start.sh`.

---

## File Structure

```
ytdl/
├── player.py          # YtdlApp (main app) + entry point
├── audio_player.py    # AudioPlayer — ffplay subprocess wrapper
├── playlist.py        # PlaylistManager — in-memory queue
├── models.py          # SearchResult dataclass + OUTPUT_DIR / RECOMMENDED_DIR / PLAYLISTS_DIR constants
├── utils.py           # song_label, normalize_title, scan_songs, yt_search, yt_radio, yt_video_id, move_to_artist_subdir, extract_artist
├── download.py        # make_ydl_opts, music filter
├── screens.py         # All modal screens (Search, Playlist, Library, SavePlaylist, SavedPlaylists, RecommendedPrompt)
├── start.sh           # Launch script (cd to dir + uses venv)
├── env/               # Python virtual environment
├── downloads/         # All downloaded MP3s
│   ├── <Artist>/
│   │   └── <Title>.mp3
│   ├── recommended/   # Songs downloaded via Recommended mode
│   │   ├── <Artist>/
│   │   │   └── <Title>.mp3
│   │   └── .archive   # yt-dlp archive (prevents re-downloads)
│   └── .archive       # yt-dlp archive for regular downloads
└── playlists/         # Saved playlists (JSON files)
    └── <name>.json
```

> `start.sh` does `cd "$(dirname "$0")"` before running `python player.py`, so all modules use simple absolute imports (`from models import ...`) without needing a package or `sys.path` manipulation.

MP3 filenames follow the pattern: `<Title>.mp3` (no YouTube ID in filename). After download, files are moved into `<Artist>/` subdirectory using `move_to_artist_subdir`.

---

## Architecture

### `AudioPlayer`
Wraps `ffplay` subprocess. Handles play, stop, pause/resume (via `SIGSTOP`/`SIGCONT`). Calls `on_end` callback when playback finishes naturally (returncode == 0). Thread-safe via `_lock`.

### `PlaylistManager`
In-memory queue of `Path` objects. Tracks a `_current` index pointer. Supports:
- `add(path)` — append to queue
- `add_next(path)` — insert right after current
- `replace_next(path)` — replace the first upcoming song (or insert if queue is empty ahead)
- `advance()` — move pointer forward, return next path
- `move_up/down(idx)` — reorder upcoming songs
- `remove(idx)` / `remove_path(path)` — remove from queue
- `clear_upcoming()` — wipe everything after current
- `jump_to_upcoming(idx)` — skip ahead in queue
- `upcoming(n)` — peek next N songs
- `all_upcoming()` — full upcoming list

### `SearchResult`
Dataclass holding either a `local_path: Path` (local file) or `yt_url: str` (YouTube). Hashable by path/URL. `is_local` property distinguishes the two types.

### Modal Screens

| Screen | Trigger | Purpose |
|---|---|---|
| `SearchScreen` | `Ctrl+F` | Combined local + YouTube search, multi-select (Space to check), add to queue or play next |
| `PlaylistScreen` | `↓` | View/reorder/delete upcoming queue |
| `LibraryScreen` | `Ctrl+L` | Browse all local songs, toggle queue membership in real time |
| `SavePlaylistScreen` | `Ctrl+S` | Name and save current queue as a JSON playlist |
| `SavedPlaylistsScreen` | `Ctrl+O` | Browse, load, or delete saved playlists |
| `RecommendedPrompt` | internal | Yes/No dialog (currently unused in main flow, was used for recommended mode toggle) |

### `YtdlApp` (main app — `player.py`)
Orchestrates everything. Key state:
- `_playlist: PlaylistManager`
- `_player: AudioPlayer`
- `_autoplay: bool` — auto-advance on song end (default: True)
- `_recommended_mode: bool` — enables YouTube-based autoqueue (mutually exclusive with autoplay)
- `_refilling: bool` — guard to prevent concurrent queue-refill operations
- `_fetch_rec_pending: bool` — guard to prevent double-triggering of manual Shift+R recommendation fetch
- `_last_played: Optional[Path]` — used as fallback for recommended query when no current song

---

## Keybindings

### Main Screen

| Key | Action |
|---|---|
| `p` | Play / Pause |
| `n` | Skip to next |
| `a` | Toggle autoplay ON/OFF |
| `r` | Toggle recommended mode ON/OFF |
| `Shift+R` (`R`) | Fetch one recommendation for current song and replace next in queue |
| `Ctrl+F` | Open search |
| `↓` | Open playlist |
| `Ctrl+L` | Open library |
| `Ctrl+O` | Open saved playlists |
| `Ctrl+S` | Save current queue as playlist |
| `Shift+L` (`L`) | Fill queue with 20 random local songs |
| `q` | Quit |

### Search Screen (`Ctrl+F`)

| Key | Action |
|---|---|
| Type | Filter local + trigger YouTube search (debounced 400ms) |
| `↑↓` | Navigate results |
| `Space` | Toggle check on item |
| `Enter` | Add checked items to end of queue |
| `Ctrl+Space` | Add checked items as play-next |
| `Tab` | Focus list |
| `Esc` | Close |

### Playlist Screen (`Ctrl+P`)

| Key | Action |
|---|---|
| `↑↓` | Navigate |
| `Ctrl+↑` | Move song up |
| `Ctrl+↓` | Move song down |
| `Enter` | Jump to and play selected song |
| `d` | Delete selected |
| `Ctrl+D` | Clear entire playlist |
| `Esc` | Close |

### Library Screen (`Ctrl+L`)

| Key | Action |
|---|---|
| Type | Filter library |
| `↑↓` | Navigate |
| `Space` | Add to end of queue / remove if already queued |
| `Ctrl+Space` | Add as play-next / remove if already queued |
| `Tab` | Focus list |
| `Esc` | Close |

---

## Core Behaviors

### Startup
On mount, 20 random local songs are loaded into the queue and playback begins immediately.

### Queue Refill
Triggered automatically when `upcoming` drops to ≤ 1 song:
- **Normal mode:** Picks 4 random local songs not already in the queue.
- **Recommended mode:** Searches YouTube based on the current song title, downloads the best match (skipping: songs too similar in title to the current song, songs already in `.archive`). Downloaded recommended songs go to `downloads/recommended/`.

### Recommended Mode
- Activated with `r`. Mutually exclusive with autoplay (turning one off turns the other on).
- Clears the upcoming queue on activation.
- Fetches the first viable recommendation immediately.
- On each new song, refills when queue runs low.
- Uses YouTube Radio/Mix (`yt_radio`) — finds the video ID of the current song via `yt_video_id`, then fetches the YouTube Radio playlist (`RD<id>`) for up to 30 candidates.
- Falls back to a random local song if no viable recommendation is found.

### YouTube Search
- Manual search uses `ytsearch25:<query>` via yt-dlp (`yt_search`).
- Deduplicates results by normalized title (strips `(Lyrics)`, `[HD]`, `(Official Video)` etc.) — keeps the result with highest view count.
- Results with `[YT]` prefix displayed in warning color (yellow) in search list.

### Download
- Format: best audio (prefers m4a/webm), converted to MP3 192kbps via FFmpeg postprocessor.
- Output path: `downloads/<title>.mp3` initially; then moved to `downloads/<artist>/<title>.mp3` via `move_to_artist_subdir` (splits on `" - "` in the filename stem).
- Download archive at `downloads/.archive` (or `recommended/.archive`) prevents re-downloading.
- Music filter (used in recommended mode): rejects audio < 90s or > 15min, and titles containing non-music keywords (podcast, interview, news, etc.).

### Song Labels & Artist Extraction
- `song_label(path)` — returns `path.stem` directly (filenames are already in `"Artist - Title"` format).
- `extract_artist(title)` — splits on `" - "` and returns the first part; returns `None` if no ` - ` is present. Used when the artist name is needed separately (e.g. future metadata tagging, grouping).

---

## UI Layout

```
┌─ Header ──────────────────────────────────────────────┐
│ ♪  NOW PLAYING                                        │  ← accent color
│ Artist - Title                                        │  ← bold
│ ▶  playing  [auto: ON]                                │  ← muted
├─ UP NEXT ─────────────────────────────────────────────┤
│   1.  Next Song                                       │
│   2.  ...                                             │  ← 20 slots shown
│   ...                                                 │
├───────────────────────────────────────────────────────┤
│ ↓  Downloading Title  45%                             │  ← dl status, success color
└─ Footer (keybindings) ────────────────────────────────┘
```

---

## Known Constraints & Gotchas

- **ffplay required** — must be installed system-wide (`ffmpeg` package usually includes it).
- **Thread safety** — `AudioPlayer` and `PlaylistManager` both use `threading.Lock`. Textual UI updates from background threads must go through `call_from_thread`.
- **`_refilling` flag** — simple boolean guard. If a download fails mid-refill, `_refilling` is reset in `except`. No timeout mechanism.
- **Playlist screen uses in-place label update** — avoids `lv.clear()` to prevent focus/selection loss on reorder. Extra items removed from the end manually.
- **Library screen uses `lv.clear()`** — acceptable since focus loss on filter-as-you-type is expected.

---

## Potential Future Development

- [ ] **Volume control** — `ffplay` doesn't expose runtime volume; would need `mpv` or a mixer approach.
- [ ] **Seek / progress bar** — `ffplay -nodisp` doesn't expose position. Switch to `mpv --no-video --input-ipc-server` for full playback control.
- [ ] **Persist queue across sessions** — serialize `_playlist._queue` to a JSON file on quit, reload on start.
- [ ] **Per-song history / last played** — track play counts or last-played timestamps in a local SQLite DB.
- [ ] **Shuffle mode** — shuffle the upcoming queue in-place.
- [ ] **Repeat one / repeat all** — repeat current song or loop the queue.
- [ ] **Smart deduplication across queue** — prevent the same song from appearing twice in the upcoming list.
- [ ] **Config file** — externalize hardcoded values (Brave cookie source, MP3 quality, music filter thresholds, initial random count).
- [ ] **Notification system** — use desktop notifications (via `notify-send`) for song changes instead of / in addition to in-app toasts.
- [ ] **Switch from `ffplay` to `mpv`** — enables: seek, volume, elapsed/remaining time display, better codec support.
- [ ] **Library deletion** — delete song from disk directly from `LibraryScreen`.
- [ ] **Import playlist from URL** — YouTube playlist URL → download all → add to queue.
