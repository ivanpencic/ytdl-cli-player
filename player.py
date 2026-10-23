#!/usr/bin/env python3
"""
ytdl player — YouTube Audio TUI
Ctrl+F: search  |  Down: playlist  |  Shift+L: fill lib
"""

import json
import random
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Label, Static

from audio_player import AudioPlayer
from download import YdlErrorLog, archived_ids, forget_archived, make_ydl_opts
from models import OUTPUT_DIR, PLAYLISTS_DIR, RECOMMENDED_DIR, SearchResult
from mpris import start_mpris
from playlist import PlaylistManager
from screens import LibraryScreen, PlaylistScreen, SavedPlaylistsScreen, SavePlaylistScreen, SearchScreen
from utils import (
    find_local, move_to_artist_subdir, normalize_title, scan_songs, song_label,
    yt_id_from_url, yt_radio, yt_video_id,
)


def _title_part(s: str) -> str:
    parts = s.split(" - ", 1)
    return parts[1].strip() if len(parts) == 2 else s


# Max candidates actually downloaded per recommendation (each may be rejected by the music filter)
MAX_REC_ATTEMPTS = 5


def _too_similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= 0.7 or a in b or b in a


class YtdlApp(App):
    CSS = """
    #main { height: 100%; padding: 1 2; }
    #now-playing {
        height: 5; border: solid $accent;
        padding: 0 1; margin-bottom: 1;
    }
    #np-header  { color: $accent; text-style: bold; }
    #np-title   { color: $text; text-style: bold; }
    #np-status  { color: $text-muted; }
    #up-next {
        height: 22; border: solid $panel;
        padding: 0 1; margin-bottom: 1;
    }
    #un-header { color: $text-muted; text-style: bold; }
    #un-list   { color: $text; }
    #dl-status { color: $success; height: 1; }
    """

    BINDINGS = [
        Binding("p",            "play_pause",         "Play/Pause",  show=True),
        Binding("n",            "skip",               "Next",        show=True),
        Binding("b",            "previous",           "Prev",        show=True),
        Binding("a",            "toggle_autoplay",    "Autoplay",    show=True),
        Binding("r",            "toggle_recommended", "Recommended", show=True),
        Binding("ctrl+f",       "search",             "Search",      show=True),
        Binding("ctrl+o",       "saved_playlists",    "Playlists",   show=True),
        Binding("ctrl+s",       "save_playlist",      "Save PL",     show=True),
        Binding("down",         "open_playlist",      "",            show=False),
        Binding("ctrl+l",       "library",            "Library",     show=True),
        Binding("L",             "fill_random",        "Fill Lib",    show=True, key_display="Shift+L"),
        Binding("R",            "fetch_recommendation","Rec Now",    show=True),
        Binding("q",            "quit",               "Quit",        show=True),
    ]

    def __init__(self):
        super().__init__()
        self._playlist = PlaylistManager()
        self._player = AudioPlayer(on_end=self._song_ended)
        self._dl_status = ""
        self._autoplay = True
        self._recommended_mode = False
        self._refilling = False
        self._fetch_rec_pending = False
        self._last_played: Optional[Path] = None
        self._mpris = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            with Container(id="now-playing"):
                yield Label("NOW PLAYING",     id="np-header")
                yield Label("nothing playing", id="np-title")
                yield Label("",               id="np-status")
            with Container(id="up-next"):
                yield Label("UP NEXT:", id="un-header")
                yield Static("",        id="un-list")
            yield Static("", id="dl-status")
        yield Footer()

    def on_mount(self):
        self._mpris = start_mpris(
            on_next=lambda: self.call_from_thread(self.action_skip),
            on_previous=lambda: self.call_from_thread(self.action_previous),
            on_play_pause=lambda: self.call_from_thread(self.action_play_pause),
            on_play=lambda: self.call_from_thread(self.action_play),
            on_pause=lambda: self.call_from_thread(self.action_pause),
        )
        self._load_random_local()
        self._refresh_main()
        if not scan_songs():
            self.call_after_refresh(self.action_search)

    def _load_random_local(self):
        songs = scan_songs()
        if not songs:
            return
        picks = random.sample(songs, min(20, len(songs)))
        for r in picks:
            self._playlist.add(r.local_path)

    # ── Download ──────────────────────────────────────────────────────────────

    def _download(
        self,
        url: str,
        title: str,
        music_only: bool = False,
        recommended: bool = False,
    ) -> tuple[Optional[Path], str]:
        """Blocking download of one video. Must run in a worker thread.

        Returns (local file, "") or (None, reason) if nothing usable exists.
        """
        if not recommended:
            path = find_local(title)
            if path:
                self._set_dl_status(f"Already downloaded: {title[:50]}")
                return path, ""
            # Archived but missing on disk means the file was deleted by hand: allow a fresh download.
            # Recommended mode keeps its archive so deleted recommendations aren't offered again.
            if forget_archived(OUTPUT_DIR, yt_id_from_url(url)):
                self._set_dl_status(f"File was deleted, downloading again: {title[:50]}")

        found: list[Path] = []
        log = YdlErrorLog()

        def progress_hook(d):
            if d["status"] == "downloading":
                name = Path(d.get("filename", "?")).stem[:40]
                pct  = d.get("_percent_str", "").strip()
                self._set_dl_status(f"Downloading  {name}  {pct}")
            elif d["status"] == "finished":
                orig = Path(d.get("filename", ""))
                if orig.name:
                    found.append(orig)

        try:
            opts = make_ydl_opts(
                progress_hook, single=True, music_only=music_only, recommended=recommended, logger=log,
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            log.last = str(e)

        files = [p for p in found if p.exists()]
        if files:
            base_dir = RECOMMENDED_DIR if recommended else OUTPUT_DIR
            self._set_dl_status(f"Done: {title[:50]}")
            return move_to_artist_subdir(files[0], base_dir), ""

        # Nothing downloaded: already in the archive (file was moved to an artist
        # subdir earlier), rejected by a filter, or a real error.
        path = find_local(title)
        if path:
            self._set_dl_status(f"Already downloaded: {title[:50]}")
            return path, ""
        reason = log.last or "skipped by filter"
        self._set_dl_status(f"Failed: {title[:40]}  ({reason[:80]})")
        return None, reason

    def _download_async(self, item: SearchResult, on_file: Callable[[Path], None]):
        """Downloads a YouTube result in the background; on_file runs on the UI thread."""
        self.notify(f"Downloading: {item.title[:50]}...", timeout=3)

        def run():
            path, reason = self._download(item.yt_url, item.title)
            if path:
                self.call_from_thread(on_file, path)
            else:
                self.call_from_thread(
                    self.notify, f"Download failed: {item.title[:50]}\n{reason}", severity="error", timeout=8
                )

        threading.Thread(target=run, daemon=True).start()

    def _set_dl_status(self, text: str):
        """Thread-safe status line update."""
        self._dl_status = text
        self.call_from_thread(self._update_dl_label)

    def _update_dl_label(self):
        try:
            self.query_one("#dl-status", Static).update(self._dl_status)
        except Exception:
            pass

    # ── Playback ──────────────────────────────────────────────────────────────

    def _song_ended(self):
        if self._autoplay or self._recommended_mode:
            self.call_from_thread(self._play_next)
        else:
            self.call_from_thread(self._refresh_main)

    def _play_next(self):
        if not self._playlist.all_upcoming():
            self._refill_queue()
            return
        path = self._playlist.advance()
        if path:
            self._last_played = path
            self._player.play(str(path))
        self._refresh_main()
        if len(self._playlist.all_upcoming()) <= 1:
            self._refill_queue()

    def _play_prev(self):
        path = self._playlist.go_back()
        if path:
            self._last_played = path
            self._player.play(str(path))
        self._refresh_main()

    def _update_mpris(self):
        if not self._mpris:
            return
        cur = self._playlist.current
        title = song_label(cur) if cur else ""
        if self._player.paused:
            status = "Paused"
        elif self._player.playing:
            status = "Playing"
        else:
            status = "Stopped"
        self._mpris.update(title, status)

    def _fetch_one_recommendation(
        self,
        cur_path: Path,
        on_found: Callable[[Path], None],
        on_not_found: Optional[Callable[[], None]] = None,
    ):
        """Fetch one YouTube recommendation for cur_path.

        Calls on_found(path) or on_not_found() on the UI thread.
        """
        current_title_norm = normalize_title(song_label(cur_path))
        rec_archived = archived_ids(RECOMMENDED_DIR)

        def run():
            try:
                all_local = scan_songs()
                local_titles = {
                    _title_part(normalize_title(song_label(r.local_path)))
                    for r in all_local
                }
                cur_t = _title_part(current_title_norm)
                vid_id = yt_video_id(song_label(cur_path))
                results = yt_radio(vid_id) if vid_id else []

                attempts = 0
                for r in results:
                    if attempts >= MAX_REC_ATTEMPTS:
                        break
                    if not r.yt_url:
                        continue
                    res_t = _title_part(normalize_title(r.title))
                    if _too_similar(cur_t, res_t):
                        continue
                    if any(_too_similar(res_t, lt) for lt in local_titles):
                        continue
                    if yt_id_from_url(r.yt_url) in rec_archived:
                        continue

                    attempts += 1
                    self.call_from_thread(self.notify, f"Rec: {r.title[:50]}", timeout=3)
                    path, _ = self._download(r.yt_url, r.title, music_only=True, recommended=True)
                    if path:
                        self.call_from_thread(on_found, path)
                        return
            except Exception:
                pass
            if on_not_found:
                self.call_from_thread(on_not_found)

        threading.Thread(target=run, daemon=True).start()

    def _refill_queue(self):
        if self._refilling:
            return
        self._refilling = True

        if self._recommended_mode:
            cur = self._playlist.current or self._last_played
            if cur is None:
                self._refilling = False
                return

            def on_found(path: Path):
                self._playlist.add(path)
                self._refilling = False
                self._refresh_main()
                if not self._player.playing:
                    self._play_next()

            def on_not_found():
                all_local = scan_songs()
                cur_t = _title_part(normalize_title(song_label(cur)))
                upcoming_paths = set(self._playlist.all_upcoming())
                candidates = [
                    r.local_path for r in all_local
                    if r.local_path not in upcoming_paths
                    and not _too_similar(cur_t, _title_part(normalize_title(song_label(r.local_path))))
                ]
                if candidates:
                    pick = random.choice(candidates)
                    self._playlist.add(pick)
                    self.notify(f"No rec found, added local: {song_label(pick)[:50]}", timeout=4)
                self._refilling = False
                self._refresh_main()
                if candidates and not self._player.playing:
                    self._play_next()

            self._fetch_one_recommendation(cur, on_found, on_not_found)

        else:
            # 4 random local songs
            all_songs = scan_songs()
            if not all_songs:
                self._refilling = False
                return
            upcoming_paths = set(self._playlist.all_upcoming())
            candidates = [r.local_path for r in all_songs if r.local_path not in upcoming_paths]
            if not candidates:
                candidates = [r.local_path for r in all_songs]
            picks = random.sample(candidates, min(4, len(candidates)))
            for p in picks:
                self._playlist.add(p)
            self._refilling = False
            self._refresh_main()
            if not self._player.playing:
                self._play_next()

    def _refresh_main(self):
        cur = self._playlist.current
        try:
            self.query_one("#np-title", Label).update(
                song_label(cur) if cur else "nothing playing"
            )
            if self._player.paused:
                status = "paused"
            elif self._player.playing:
                status = "playing"
            else:
                status = ""
            flags = []
            if self._recommended_mode:
                flags.append("rec: ON")
            else:
                flags.append(f"auto: {'ON' if self._autoplay else 'OFF'}")
            self.query_one("#np-status", Label).update(
                f"{status}  [{' | '.join(flags)}]" if status else f"[{' | '.join(flags)}]"
            )
            lines = []
            for i, s in enumerate(self._playlist.upcoming(20), 1):
                lines.append(f"  {i}.  {song_label(s)}")
            while len(lines) < 20:
                lines.append(f"  {len(lines) + 1}.  -")
            self.query_one("#un-list", Static).update("\n".join(lines))
        except Exception:
            pass
        self._update_mpris()

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_play_pause(self):
        if not self._player.playing:
            self._play_next()
        else:
            self._player.toggle_pause()
            self._refresh_main()

    def action_play(self):
        if self._player.paused:
            self._player.resume()
            self._refresh_main()
        elif not self._player.playing:
            self._play_next()

    def action_pause(self):
        self._player.pause()
        self._refresh_main()

    def action_toggle_autoplay(self):
        self._autoplay = not self._autoplay
        if self._autoplay and self._recommended_mode:
            self._recommended_mode = False
            self.notify("Autoplay ON  |  Recommended OFF", timeout=2)
        else:
            self.notify(f"Autoplay {'ON' if self._autoplay else 'OFF'}", timeout=2)
        self._refresh_main()

    def action_toggle_recommended(self):
        self._recommended_mode = not self._recommended_mode
        if self._recommended_mode:
            self._autoplay = False
            self._playlist.clear_upcoming()
            self._refilling = False
            self._refill_queue()
            self.notify("Recommended ON - queue cleared, fetching recommendation...", timeout=4)
        else:
            self._autoplay = True
            self.notify("Recommended OFF  |  Autoplay ON", timeout=2)
        self._refresh_main()

    def action_skip(self):
        self._play_next()

    def action_previous(self):
        self._play_prev()

    def action_search(self):
        if len(self.screen_stack) > 1:
            return
        local = scan_songs()
        self.push_screen(SearchScreen(local), self._on_search_result)

    def _on_search_result(self, result):
        if not result:
            return
        action, items = result

        if action == "play_now":
            item = items[0]
            if item.is_local:
                self._play_now(item.local_path)
            else:
                self._download_async(item, self._play_now)
            return

        for item in items:
            if item.is_local:
                self._enqueue(item.local_path, action)
            else:
                self._download_async(item, lambda path, a=action: self._on_queued_download(path, a))

        if self._playlist.current is None and self._playlist.all_upcoming():
            self._play_next()
        else:
            self._refresh_main()

    def _play_now(self, path: Path):
        """Puts path at the front of the queue and starts it immediately."""
        self._playlist.add_next(path)
        self._play_next()

    def _enqueue(self, path: Path, action: str):
        if action == "next":
            self._playlist.add_next(path)
        else:
            self._playlist.add(path)

    def _on_queued_download(self, path: Path, action: str):
        self._enqueue(path, action)
        self.notify(f"Added: {song_label(path)[:50]}", timeout=3)
        if self._playlist.current is None:
            self._play_next()
        else:
            self._refresh_main()

    def action_open_playlist(self):
        """Opens playlist only from the main screen (↓ key)."""
        if len(self.screen_stack) > 1:
            return
        self.action_playlist()

    def action_playlist(self):
        if not self._playlist.all_upcoming():
            self.notify("Playlist is empty.", severity="warning")
            return
        self.push_screen(PlaylistScreen(self._playlist), self._on_playlist_result)

    def _on_playlist_result(self, result):
        if isinstance(result, tuple) and result[0] == "play":
            idx = result[1]
            self._player.stop()
            self._playlist.jump_to_upcoming(idx)
            self._play_next()
        else:
            self._refresh_main()

    def action_library(self):
        if len(self.screen_stack) > 1:
            return
        songs = scan_songs()
        if not songs:
            self.notify("No downloaded songs.", severity="warning")
            return
        self.push_screen(LibraryScreen(songs, self._playlist), lambda _: self._refresh_main())

    def action_saved_playlists(self):
        if len(self.screen_stack) > 1:
            return
        self.push_screen(SavedPlaylistsScreen(), self._on_saved_playlists_result)

    def _on_saved_playlists_result(self, songs):
        if not songs:
            return
        self._playlist.clear_upcoming()
        for p in songs:
            self._playlist.add(p)
        self.notify(f"Loaded {len(songs)} songs.", timeout=2)
        self._refresh_main()
        if not self._player.playing:
            self._play_next()

    def action_save_playlist(self):
        if len(self.screen_stack) > 1:
            return
        songs = self._playlist.all_upcoming()
        if not songs:
            self.notify("Queue is empty.", severity="warning")
            return
        self.push_screen(SavePlaylistScreen(), lambda name: self._do_save_playlist(name, list(songs)))

    def _do_save_playlist(self, name: Optional[str], songs: list):
        if not name:
            return
        PLAYLISTS_DIR.mkdir(exist_ok=True)
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
        path = PLAYLISTS_DIR / f"{safe}.json"
        path.write_text(json.dumps({"name": name, "songs": [str(p) for p in songs]}, indent=2))
        self.notify(f"Saved: {name} ({len(songs)} songs)", timeout=2)

    def action_fill_random(self):
        songs = scan_songs()
        if not songs:
            self.notify("No local songs found.", severity="warning")
            return
        upcoming = set(self._playlist.all_upcoming())
        candidates = [r.local_path for r in songs if r.local_path not in upcoming]
        if not candidates:
            candidates = [r.local_path for r in songs]
        picks = random.sample(candidates, min(20, len(candidates)))
        for p in picks:
            self._playlist.add(p)
        self.notify(f"Added {len(picks)} random songs to queue.", timeout=2)
        self._refresh_main()
        if not self._player.playing:
            self._play_next()

    def action_fetch_recommendation(self):
        cur = self._playlist.current or self._last_played
        if cur is None:
            self.notify("Nothing playing.", severity="warning")
            return
        if self._fetch_rec_pending:
            self.notify("Already fetching...", timeout=2)
            return
        self._fetch_rec_pending = True
        self.notify(f"Fetching recommendation for: {song_label(cur)[:50]}", timeout=3)

        def on_found(path: Path):
            self._playlist.replace_next(path)
            self._fetch_rec_pending = False
            self._refresh_main()

        def on_not_found():
            self._fetch_rec_pending = False
            self.notify("No recommendation found.", severity="warning", timeout=3)

        self._fetch_one_recommendation(cur, on_found, on_not_found)

    def action_quit(self):
        self.exit()

    def shutdown(self):
        """Stops ffplay and MPRIS; runs however the app exits (q, Ctrl+C, crash)."""
        self._player.stop()
        if self._mpris:
            self._mpris.stop()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = YtdlApp()
    try:
        app.run()
    finally:
        app.shutdown()
