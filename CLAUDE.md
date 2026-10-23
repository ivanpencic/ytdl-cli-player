# ytdl player — CLAUDE.md

> **IMPORTANT:** Whenever `player.py` is modified (new features, refactors, bug fixes, keybinding changes), update this file to reflect the current state of the codebase.

## Overview

Terminal-based YouTube audio player (TUI) built with [Textual](https://textual.textualize.io/). Downloads audio via `yt-dlp` in native format (opus/webm preferred, m4a fallback) and plays with `ffplay` (part of FFmpeg). All playback is offline after download.

**Entry point:** `start.sh` → `env/bin/python player.py`

---

## Dependencies

| Tool / Library | Role |
|---|---|
| `yt-dlp[default]` | YouTube search and audio download (includes `yt-dlp-ejs` for YouTube JS challenges) |
| `node` or `deno` | JS runtime yt-dlp uses to solve YouTube challenges (`node` is auto-detected via `shutil.which`) |
| `ffplay` | Audio playback |
| `textual` | Terminal UI framework |

Python venv is at `env/`. Activate with `source env/bin/activate` or run via `start.sh`.

---

## File Structure

```
ytdl/
├── player.py          # YtdlApp (main app) + entry point
├── audio_player.py    # AudioPlayer — ffplay subprocess wrapper
├── playlist.py        # PlaylistManager — in-memory queue
├── models.py          # SearchResult dataclass + OUTPUT_DIR / RECOMMENDED_DIR / PLAYLISTS_DIR / YT_PREFIX constants
├── utils.py           # song_label, delete_song_file, normalize_title, scan_songs, yt_search, yt_radio, yt_video_id, yt_id_from_url, move_to_artist_subdir, extract_artist, yt_filename_stem, find_local
├── mpris.py           # MPRIS2 D-Bus service (media keys / Bluetooth controls), optional
├── download.py        # make_ydl_opts, music filter, YdlErrorLog, archived_ids / forget_archived
├── screens.py         # All modal screens (Search, Playlist, Library, SavePlaylist, SavedPlaylists, ConfirmPrompt)
├── start.sh           # Launch script (cd to dir + uses venv)
├── env/               # Python virtual environment
├── downloads/         # All downloaded audio files (webm/m4a)
│   ├── <Artist>/
│   │   └── <Title>.<ext>
│   ├── recommended/   # Songs downloaded via Recommended mode
│   │   ├── <Artist>/
│   │   │   └── <Title>.<ext>
│   │   └── .archive   # yt-dlp archive (prevents re-downloads)
│   └── .archive       # yt-dlp archive for regular downloads
└── playlists/         # Saved playlists (JSON files)
    └── <name>.json
```

> `start.sh` does `cd "$(dirname "$0")"` before running `python player.py`, so all modules use simple absolute imports (`from models import ...`) without needing a package or `sys.path` manipulation.

Filenames follow the pattern: `<Title>.<ext>` (no YouTube ID in filename). After download, files are moved into `<Artist>/` subdirectory using `move_to_artist_subdir`.

---

## Architecture

### `AudioPlayer`
Wraps `ffplay` subprocess. Handles play, stop, pause/resume (via `SIGSTOP`/`SIGCONT`). Calls `on_end` callback when playback finishes naturally (returncode == 0). Thread-safe via `_lock`. Each waiter thread receives its own `proc` so a stale waiter can never fire `on_end` for a newer process.

### `PlaylistManager`
In-memory queue of `Path` objects. Tracks a `_current` index pointer. Supports:
- `add(path)` — append to queue
- `add_next(path)` — insert right after current
- `replace_next(path)` — replace the first upcoming song (or insert if queue is empty ahead)
- `advance()` — move pointer forward, return next path
- `move_up/down(idx)` — reorder upcoming songs
- `remove(idx)` / `remove_path(path)` — remove from queue
- `remove_all(path)` — remove every upcoming occurrence of path
- `clear_upcoming()` — wipe everything after current
- `jump_to_upcoming(idx)` — skip ahead in queue
- `upcoming(n)` — peek next N songs
- `all_upcoming()` — full upcoming list

### `SearchResult`
Dataclass holding either a `local_path: Path` (local file) or `yt_url: str` (YouTube). Hashable by path/URL. `is_local` property distinguishes the two types; `title` returns `display` without the `[YT]  ` prefix.

### Modal Screens

| Screen | Trigger | Purpose |
|---|---|---|
| `SearchScreen` | `Ctrl+F` | Combined local + YouTube search. Enter: play highlighted now, or append checked items to queue |
| `PlaylistScreen` | `↓` | View/reorder/delete upcoming queue |
| `LibraryScreen` | `Ctrl+L` | Browse all local songs, toggle queue membership in real time |
| `SavePlaylistScreen` | `Ctrl+S` | Name and save current queue as a JSON playlist |
| `SavedPlaylistsScreen` | `Ctrl+O` | Browse, load, or delete saved playlists |
| `ConfirmPrompt` | internal | Generic Yes/No dialog (`ConfirmPrompt(message, default=False)`), dismisses with bool. Used before deleting files |

### `YtdlApp` (main app — `player.py`)
Orchestrates everything. Key state:
- `_playlist: PlaylistManager`
- `_player: AudioPlayer`
- `_autoplay: bool` — auto-advance on song end (default: True)
- `_recommended_mode: bool` — enables YouTube-based autoqueue (mutually exclusive with autoplay)
- `_refilling: bool` — guard to prevent concurrent queue-refill operations
- `_fetch_rec_pending: bool` — guard to prevent double-triggering of manual Shift+R recommendation fetch
- `_last_played: Optional[Path]` — used as fallback for recommended query when no current song

Download helpers:
- `_download(url, title, music_only, recommended)` — blocking (worker threads only). For manual downloads it first returns an existing local file (`find_local`) without touching the network; if the ID is archived but the file is gone, it removes the ID from `downloads/.archive` (`forget_archived`) and downloads again. Downloads one video, moves it into `<Artist>/`, returns `(path, "")`. If yt-dlp produced nothing (archive hit or filter rejection) falls back to `find_local(title)`; otherwise returns `(None, reason)` where reason is the last yt-dlp error captured by `YdlErrorLog` (shown in the failure toast).
- `_download_async(item, on_file)` — runs `_download` in a thread; `on_file(path)` is called on the UI thread.
- `_fetch_one_recommendation` — tries up to `MAX_REC_ATTEMPTS` (5) radio candidates sequentially until one downloads; `on_found` / `on_not_found` are called on the UI thread.

---

## Keybindings

### Main Screen

| Key | Action |
|---|---|
| `p` | Play / Pause |
| `n` | Skip to next |
| `b` | Previous song |
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
| `Enter` (nothing checked) | Play highlighted item now: download if YouTube, insert at queue front, start playing. From the input box, the top result is used |
| `Enter` (items checked) | Download (if YouTube) and append checked items to end of queue, in check order |
| `Ctrl+N` | Highlighted item (checked items ignored) plays next, without interrupting the current song |
| `Shift+Enter` | Same as `Ctrl+N`, only in terminals that report Shift+Enter (kitty keyboard protocol). Most terminals (and Alt+Enter) send plain Enter, which plays immediately |
| `Tab` | Focus list |
| `Esc` | Close |

### Playlist Screen (`↓`)

| Key | Action |
|---|---|
| `↑↓` | Navigate |
| `Ctrl+↑` | Move song up |
| `Ctrl+↓` | Move song down |
| `Enter` | Jump to and play selected song |
| `d` | Remove selected from queue |
| `Shift+Delete` | Delete selected file from disk (asks for confirmation, default No); removes all its occurrences from the queue and an artist folder left empty |
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
- Activated with `r`. Mutually exclusive with autoplay: turning recommended on disables autoplay, turning it off re-enables autoplay.
- Clears the upcoming queue on activation.
- Fetches the first viable recommendation immediately.
- On each new song, refills when queue runs low.
- Uses YouTube Radio/Mix (`yt_radio`) — finds the video ID of the current song via `yt_video_id`, then fetches the YouTube Radio playlist (`RD<id>`) for up to 30 candidates.
- Downloads candidates sequentially (max 5 attempts) — a candidate rejected by the music filter moves on to the next one instead of stalling the refill.
- Falls back to a random local song if no viable recommendation is found.

### YouTube Search
- Manual search uses `ytsearch25:<query>` via yt-dlp (`yt_search`).
- Deduplicates results by normalized title (strips `(Lyrics)`, `[HD]`, `(Official Video)` etc.) — keeps the result with highest view count.
- YouTube results whose yt-dlp filename (`yt_filename_stem`) matches an existing local file are shown as that local item, so already-downloaded songs are never re-requested.
- Stale YouTube results (query changed while the search ran) are discarded.
- Results with `[YT]` prefix displayed in warning color (yellow, `.yt-item`) in search list.

### Download
- Format: best audio (prefers opus/webm, fallback m4a), no conversion — native format kept.
- Output path: `downloads/<title>.<ext>` initially; then moved to `downloads/<artist>/<title>.<ext>` via `move_to_artist_subdir` (splits on `" - "` in the filename stem).
- Download archive at `downloads/.archive` (or `recommended/.archive`) prevents re-downloading. On an archive hit the existing file is located via `find_local`.
- **Deleted files:** the library is never stored — it is rescanned from disk each time, so deleting a file removes it everywhere. For manual downloads a stale archive entry (ID archived, file missing) is dropped and the song is downloaded again. `recommended/.archive` is intentionally left alone so deleted recommendations aren't offered again.
- Local-file matching is by filename (`yt_filename_stem(title)`), so a renamed file is treated as missing and gets downloaded again.
- Music filter (used in recommended mode): rejects audio < 90s or > 15min, and titles containing non-music keywords (podcast, interview, news, etc.).

### Song Labels & Artist Extraction
- `song_label(path)` — returns `path.stem` directly (filenames are already in `"Artist - Title"` format).
- `extract_artist(title)` — splits on `" - "` and returns the first part; returns `None` if no ` - ` is present. Used when the artist name is needed separately (e.g. future metadata tagging, grouping).

---

## UI Layout

```
┌─ Header ──────────────────────────────────────────────┐
│ NOW PLAYING                                           │  ← accent color
│ Artist - Title                                        │  ← bold
│ playing  [auto: ON]                                   │  ← muted
├─ UP NEXT ─────────────────────────────────────────────┤
│   1.  Next Song                                       │
│   2.  ...                                             │  ← 20 slots shown
│   ...                                                 │
├───────────────────────────────────────────────────────┤
│ Downloading  Title  45%                               │  ← dl status, success color
└─ Footer (keybindings) ────────────────────────────────┘
```

---

## Known Constraints & Gotchas

- **ffplay required** — must be installed system-wide (`ffmpeg` package usually includes it).
- **Keep yt-dlp current** — an outdated yt-dlp gets `HTTP Error 403: Forbidden` from YouTube. `init.sh` always runs `pip install -U "yt-dlp[default]"`.
- **Thread safety** — `AudioPlayer` and `PlaylistManager` both use `threading.Lock`. Textual UI updates from background threads must go through `call_from_thread`.
- **`_refilling` flag** — simple boolean guard. If a download fails mid-refill, `_refilling` is reset in `except`. No timeout mechanism.
- **Playlist screen uses in-place label update** — avoids `lv.clear()` to prevent focus/selection loss on reorder. Extra items removed from the end manually.
- **Library screen uses `lv.clear()`** — acceptable since focus loss on filter-as-you-type is expected.
- **No Unicode symbols in UI strings** — use plain words / ASCII (`[x]`, `[ ]`, `playing`, `paused`).
- **MPRIS** — `Play`/`Pause`/`Stop` map to `action_play`/`action_pause` (idempotent); only `PlayPause` toggles.
- **Shutdown** — `YtdlApp.shutdown()` runs in a `finally` around `app.run()`, so ffplay is killed on any exit path.

---

## Potential Future Development

- [ ] **Volume control** — `ffplay` doesn't expose runtime volume; would need `mpv` or a mixer approach.
- [ ] **Seek / progress bar** — `ffplay -nodisp` doesn't expose position. Switch to `mpv --no-video --input-ipc-server` for full playback control.
- [ ] **Persist queue across sessions** — serialize `_playlist._queue` to a JSON file on quit, reload on start.
- [ ] **Per-song history / last played** — track play counts or last-played timestamps in a local SQLite DB.
- [ ] **Shuffle mode** — shuffle the upcoming queue in-place.
- [ ] **Repeat one / repeat all** — repeat current song or loop the queue.
- [ ] **Smart deduplication across queue** — prevent the same song from appearing twice in the upcoming list.
- [ ] **Config file** — externalize hardcoded values (music filter thresholds, initial random count, preferred audio format).
- [ ] **Notification system** — use desktop notifications (via `notify-send`) for song changes instead of / in addition to in-app toasts.
- [ ] **Switch from `ffplay` to `mpv`** — enables: seek, volume, elapsed/remaining time display, better codec support.
- [ ] **Library deletion** — delete song from disk directly from `LibraryScreen` (Playlist screen already has `Shift+Delete`; reuse `ConfirmPrompt` + `delete_song_file`).
- [ ] **Import playlist from URL** — YouTube playlist URL → download all → add to queue.
