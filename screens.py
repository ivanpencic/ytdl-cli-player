import json
import time
from pathlib import Path
from typing import List, Optional

from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from models import PLAYLISTS_DIR, SearchResult
from playlist import PlaylistManager
from utils import delete_song_file, song_label, yt_filename_stem, yt_search


# ─── Confirm Prompt ───────────────────────────────────────────────────────────

class ConfirmPrompt(ModalScreen):
    """Yes/No dialog. Dismisses with True (yes) or False (no / Esc)."""

    CSS = """
    ConfirmPrompt { align: center middle; }
    #cp-box {
        width: 70; height: auto;
        background: $surface;
        border: solid $error;
        padding: 1 4;
    }
    #cp-title  { width: 100%; text-align: center; text-style: bold; margin-bottom: 1; }
    #cp-opts   { width: 100%; height: 3; align: center middle; }
    .cp-btn    { width: 20; height: 3; border: solid $panel; content-align: center middle; margin: 0 1; }
    .cp-active { border: solid $accent; color: $accent; text-style: bold; }
    """
    BINDINGS = [
        Binding("left",   "pick_yes", "", show=False),
        Binding("right",  "pick_no",  "", show=False),
        Binding("y",      "pick_yes", "", show=False),
        Binding("n",      "pick_no",  "", show=False),
        Binding("enter",  "confirm",  "Confirm", priority=True),
        Binding("escape", "cancel",   "Cancel"),
    ]

    _choice: reactive[bool] = reactive(False)

    def __init__(self, message: str, default: bool = False):
        super().__init__()
        self._message = message
        self._default = default

    def compose(self) -> ComposeResult:
        with Container(id="cp-box"):
            yield Label(self._message, id="cp-title")
            with Horizontal(id="cp-opts"):
                yield Static("Yes", id="cp-yes", classes="cp-btn")
                yield Static("No",  id="cp-no",  classes="cp-btn")

    def on_mount(self):
        self._choice = self._default
        self.watch__choice(self._choice)

    def watch__choice(self, val: bool):
        try:
            self.query_one("#cp-yes", Static).set_class(val, "cp-active")
            self.query_one("#cp-no",  Static).set_class(not val, "cp-active")
        except Exception:
            pass

    def action_pick_yes(self):
        self._choice = True

    def action_pick_no(self):
        self._choice = False

    def action_play_highlighted_next(self):
        """Queues the highlighted song right after the current one, ignoring checked items."""
        item = self._highlighted()
        if item:
            self.dismiss(("next", [item]))

    def action_confirm(self):
        self.dismiss(self._choice)

    def action_cancel(self):
        self.dismiss(False)


# ─── Search Screen ────────────────────────────────────────────────────────────

class SearchScreen(ModalScreen):
    """Ctrl+F — local + YouTube search.

    Enter with nothing checked plays the highlighted song immediately (downloading it
    first if needed). Enter with checked songs appends them to the queue.
    """

    CSS = """
    SearchScreen { align: center middle; }
    #sb-box {
        width: 88%; height: 80%;
        background: $surface;
        border: solid $accent;
        padding: 1 2;
    }
    #sb-title  { text-style: bold; margin-bottom: 1; }
    #sb-hint   { color: $text-muted; margin-bottom: 1; }
    #sb-input  { margin-bottom: 1; }
    #sb-status { color: $text-muted; height: 1; margin-bottom: 1; }
    #sb-list   { height: 1fr; }
    .yt-item   { color: $warning; }
    """

    BINDINGS = [
        Binding("enter",       "confirm",              "Play / Add checked", priority=True),
        # Most terminals send Shift+Enter as plain Enter; Ctrl+N works everywhere
        Binding("ctrl+n",      "play_highlighted_next", "Next (highlighted)", priority=True),
        Binding("shift+enter", "play_highlighted_next", "", show=False, priority=True),
        Binding("escape",     "dismiss",    "Close"),
        Binding("tab",        "focus_list", "List"),
    ]

    MAX_SHOWN = 200

    def __init__(self, local: List[SearchResult]):
        super().__init__()
        self._local = local
        self._local_by_stem = {r.local_path.stem: r for r in local}
        self._results: List[SearchResult] = list(local)
        self._checked: List[SearchResult] = []
        self._current_query = ""

    def compose(self) -> ComposeResult:
        with Container(id="sb-box"):
            yield Label("Search  (local + YouTube)", id="sb-title")
            yield Label(
                "Up/Down: navigate  |  Space: check  |  Enter: play highlighted now / add checked to queue"
                "  |  Ctrl+N: highlighted plays next  |  Esc: close",
                id="sb-hint",
            )
            yield Input(placeholder="Song name...", id="sb-input")
            yield Static("", id="sb-status")
            yield ListView(id="sb-list")

    def on_mount(self):
        self.query_one("#sb-input", Input).focus()
        self._refresh_list()

    @on(Input.Changed)
    def _on_input(self, event: Input.Changed):
        q = event.value.strip()
        self._current_query = q
        if not q:
            self._results = list(self._local)
            self._set_status("")
            self._refresh_list()
            return
        self._results = [r for r in self._local if q.lower() in r.display.lower()]
        self._set_status("Searching YouTube...")
        self._refresh_list()
        self._yt_search(q)

    @work(thread=True, exclusive=True)
    def _yt_search(self, query: str) -> None:
        time.sleep(0.4)
        if self._current_query != query:
            return
        results = yt_search(query)
        self.app.call_from_thread(self._add_yt_results, query, results)

    def _add_yt_results(self, query: str, yt: List[SearchResult]):
        # Thread workers can't be interrupted, so a slow search may finish after the query changed
        if query != self._current_query:
            return
        shown = set(self._results)
        new: List[SearchResult] = []
        for r in yt:
            # Songs already on disk are offered as local items instead of being downloaded again
            r = self._local_by_stem.get(yt_filename_stem(r.title), r)
            if r not in shown:
                shown.add(r)
                new.append(r)
        self._results = self._results + new
        yt_count = sum(1 for r in new if not r.is_local)
        self._set_status(f"Found {yt_count} YouTube results" if yt_count else "No new YouTube results")
        self._refresh_list(keep_index=self.query_one("#sb-list", ListView).index)

    def _set_status(self, text: str):
        try:
            self.query_one("#sb-status", Static).update(text)
        except Exception:
            pass

    def _refresh_list(self, keep_index: Optional[int] = None):
        lv = self.query_one("#sb-list", ListView)
        lv.clear()
        for r in self._results[:self.MAX_SHOWN]:
            mark = "[x]" if r in self._checked else "[ ]"
            classes = "" if r.is_local else "yt-item"
            lv.append(ListItem(Label(f"  {mark}  {r.display}", classes=classes)))
        if keep_index is not None:
            self.call_after_refresh(lambda: setattr(lv, "index", keep_index))

    def _toggle_at(self, idx: int):
        if idx < len(self._results):
            r = self._results[idx]
            if r in self._checked:
                self._checked.remove(r)
            else:
                self._checked.append(r)
            self._refresh_list(keep_index=idx)

    def _highlighted(self) -> Optional[SearchResult]:
        """Highlighted list item; from the input box this falls back to the top result."""
        lv = self.query_one("#sb-list", ListView)
        idx = lv.index
        if idx is None and not lv.has_focus:
            idx = 0
        if idx is not None and idx < min(len(self._results), self.MAX_SHOWN):
            return self._results[idx]
        return None

    def on_key(self, event: events.Key):
        lv = self.query_one("#sb-list", ListView)
        inp = self.query_one("#sb-input", Input)
        if event.key == "space" and not inp.has_focus:
            idx = lv.index
            if idx is not None:
                event.prevent_default()
                event.stop()
                self._toggle_at(idx)
        elif event.key == "down" and inp.has_focus:
            event.stop()
            self.action_focus_list()
        elif event.key == "up" and lv.has_focus and lv.index == 0:
            event.stop()
            inp.focus()

    def action_focus_list(self):
        lv = self.query_one("#sb-list", ListView)
        lv.focus()
        if lv.index is None and self._results:
            lv.index = 0

    def action_play_highlighted_next(self):
        """Queues the highlighted song right after the current one, ignoring checked items."""
        item = self._highlighted()
        if item:
            self.dismiss(("next", [item]))

    def action_confirm(self):
        if self._checked:
            self.dismiss(("queue", list(self._checked)))
            return
        item = self._highlighted()
        if item:
            self.dismiss(("play_now", [item]))


# ─── Playlist Screen ──────────────────────────────────────────────────────────

class PlaylistScreen(ModalScreen):
    CSS = """
    PlaylistScreen { align: center middle; }
    #pl-box {
        width: 85%; height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #pl-title { text-style: bold; margin-bottom: 1; }
    #pl-hint  { color: $text-muted; margin-bottom: 1; }
    #pl-list  { height: 1fr; }
    """
    BINDINGS = [
        Binding("escape",    "dismiss",       "Close"),
        Binding("enter",     "play_selected", "Play",      show=True, priority=True),
        Binding("ctrl+up",   "move_up",       "Move up"),
        Binding("ctrl+down", "move_down",     "Move down"),
        Binding("d",         "delete",        "Delete"),
        Binding("delete",    "delete",        "",          show=False),
        Binding("shift+delete", "delete_file", "Delete file"),
        Binding("ctrl+d",    "delete_all",    "Delete all"),
    ]

    def __init__(self, playlist: PlaylistManager):
        super().__init__()
        self._playlist = playlist

    def compose(self) -> ComposeResult:
        songs = self._playlist.all_upcoming()
        with Container(id="pl-box"):
            yield Label(f"Playlist - {len(songs)} songs in queue", id="pl-title")
            yield Label(
                "Up/Down: navigate  |  Ctrl+Up/Down: reorder  |  Enter: play  |  d: remove  |  Shift+Del: delete file"
                "  |  Ctrl+D: clear all  |  Esc: close",
                id="pl-hint",
            )
            yield ListView(id="pl-list")

    def on_mount(self):
        self._refresh_list()
        self.query_one("#pl-list", ListView).focus()

    def _refresh_list(self, keep_index: int = 0):
        songs = self._playlist.all_upcoming()
        lv = self.query_one("#pl-list", ListView)
        items = list(lv.query(ListItem))

        # Update labels of existing items (avoids clear → focus/selection loss)
        for i, song in enumerate(songs):
            text = f"  {i + 1:>3}.  {song_label(song)}"
            if i < len(items):
                try:
                    items[i].query_one(Label).update(text)
                except Exception:
                    pass
            else:
                lv.append(ListItem(Label(text)))

        # Remove leftover items from the end
        for item in items[len(songs):]:
            item.remove()

        count = len(songs)
        if count > 0:
            target = min(keep_index, count - 1) if keep_index is not None else 0

            def _restore():
                lv.focus()
                lv.index = target

            self.call_after_refresh(_restore)

    def action_move_up(self):
        lv = self.query_one("#pl-list", ListView)
        idx = lv.index
        if idx is not None and idx > 0:
            self._playlist.move_up(idx)
            self._refresh_list(keep_index=idx - 1)

    def action_move_down(self):
        lv = self.query_one("#pl-list", ListView)
        idx = lv.index
        if idx is not None and idx < len(self._playlist.all_upcoming()) - 1:
            self._playlist.move_down(idx)
            self._refresh_list(keep_index=idx + 1)

    def _update_title(self):
        songs = self._playlist.all_upcoming()
        try:
            self.query_one("#pl-title", Label).update(
                f"Playlist - {len(songs)} songs in queue"
            )
        except Exception:
            pass

    def action_delete(self):
        lv = self.query_one("#pl-list", ListView)
        idx = lv.index
        if idx is None:
            return
        self._playlist.remove(idx)
        songs = self._playlist.all_upcoming()
        new_idx = min(idx, len(songs) - 1) if songs else None
        self._refresh_list(keep_index=new_idx)
        self._update_title()

    def action_delete_file(self):
        lv = self.query_one("#pl-list", ListView)
        idx = lv.index
        songs = self._playlist.all_upcoming()
        if idx is None or idx >= len(songs):
            return
        path = songs[idx]
        self.app.push_screen(
            ConfirmPrompt(f"Delete file from disk?\n\n{song_label(path)}"),
            lambda yes: self._delete_file(idx, path) if yes else None,
        )

    def _delete_file(self, idx: int, path: Path):
        try:
            delete_song_file(path)
        except OSError as e:
            self.notify(f"Delete failed: {e}", severity="error", timeout=5)
            return
        self._playlist.remove_all(path)
        songs = self._playlist.all_upcoming()
        self._refresh_list(keep_index=min(idx, len(songs) - 1) if songs else None)
        self._update_title()
        self.notify(f"Deleted: {song_label(path)[:50]}", timeout=3)

    def action_play_selected(self):
        lv = self.query_one("#pl-list", ListView)
        idx = lv.index
        if idx is not None:
            self.dismiss(("play", idx))

    def action_delete_all(self):
        self._playlist.clear_upcoming()
        self._refresh_list(keep_index=None)
        self._update_title()
        self.notify("Playlist cleared.", timeout=2)


# ─── Library Screen ───────────────────────────────────────────────────────────

class LibraryScreen(ModalScreen):
    """All downloaded songs — Space adds/removes from queue live"""

    CSS = """
    LibraryScreen { align: center middle; }
    #lib-box {
        width: 88%; height: 85%;
        background: $surface;
        border: solid $success;
        padding: 1 2;
    }
    #lib-title  { text-style: bold; margin-bottom: 1; }
    #lib-hint   { color: $text-muted; margin-bottom: 1; }
    #lib-filter { margin-bottom: 1; }
    #lib-list   { height: 1fr; }
    .in-queue   { color: $warning; }
    """

    BINDINGS = [
        Binding("escape", "dismiss",    "Close"),
        Binding("tab",    "focus_list", "List"),
    ]

    def __init__(self, songs: List[SearchResult], playlist: PlaylistManager):
        super().__init__()
        self._all = songs
        self._filtered = list(songs)
        self._playlist = playlist

    def compose(self) -> ComposeResult:
        with Container(id="lib-box"):
            yield Label(f"Library - {len(self._all)} songs", id="lib-title")
            yield Label(
                "Up/Down: navigate  |  Space: add to end / remove  |  Ctrl+Space: add to front / remove  |  Esc: close",
                id="lib-hint",
            )
            yield Input(placeholder="Filter...", id="lib-filter")
            yield ListView(id="lib-list")

    def on_mount(self):
        self.query_one("#lib-filter", Input).focus()
        self._refresh_list()

    @on(Input.Changed)
    def _on_filter(self, event: Input.Changed):
        q = event.value.strip().lower()
        self._filtered = [r for r in self._all if q in r.display.lower()] if q else list(self._all)
        self._refresh_list()

    def _queue_pos_map(self) -> dict:
        """Path → position (1-based) in upcoming queue."""
        pos: dict[Path, int] = {}
        for i, p in enumerate(self._playlist.all_upcoming(), 1):
            if p not in pos:
                pos[p] = i
        return pos

    def _refresh_list(self, keep_index: Optional[int] = None):
        queue_pos = self._queue_pos_map()
        lv = self.query_one("#lib-list", ListView)
        lv.clear()
        for r in self._filtered:
            p = r.local_path
            pos = queue_pos.get(p) if p else None
            if pos is not None:
                label = Label(f"  [x]  [{pos:>3}]  {r.display}", classes="in-queue")
            else:
                label = Label(f"  [ ]         {r.display}")
            lv.append(ListItem(label))
        if keep_index is not None:
            self.call_after_refresh(lambda: setattr(lv, "index", keep_index))

    def _toggle_at(self, idx: int, front: bool = False):
        if idx >= len(self._filtered):
            return
        r = self._filtered[idx]
        if r.local_path is None:
            return
        queue_pos = self._queue_pos_map()
        if r.local_path in queue_pos:
            self._playlist.remove_path(r.local_path)
        else:
            if front:
                self._playlist.add_next(r.local_path)
            else:
                self._playlist.add(r.local_path)
        self._refresh_list(keep_index=idx)
        try:
            self.app._refresh_main()
        except Exception:
            pass

    def on_key(self, event: events.Key):
        lv = self.query_one("#lib-list", ListView)
        inp = self.query_one("#lib-filter", Input)
        if event.key == "space" and not inp.has_focus:
            idx = lv.index
            if idx is not None:
                event.prevent_default()
                event.stop()
                self._toggle_at(idx, front=False)
        elif event.key == "ctrl+space" and not inp.has_focus:
            idx = lv.index
            if idx is not None:
                event.prevent_default()
                event.stop()
                self._toggle_at(idx, front=True)
        elif event.key == "down" and inp.has_focus:
            event.stop()
            self.action_focus_list()
        elif event.key == "up" and lv.has_focus and lv.index == 0:
            event.stop()
            inp.focus()

    def action_focus_list(self):
        lv = self.query_one("#lib-list", ListView)
        lv.focus()
        if lv.index is None and self._filtered:
            lv.index = 0


# ─── Save Playlist Screen ─────────────────────────────────────────────────────

class SavePlaylistScreen(ModalScreen):
    CSS = """
    SavePlaylistScreen { align: center middle; }
    #savpl-box {
        width: 60; height: 12;
        background: $surface;
        border: solid $accent;
        padding: 1 2;
    }
    #savpl-title { text-style: bold; margin-bottom: 1; }
    """
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("enter",  "confirm", "Save",   priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="savpl-box"):
            yield Label("Save Playlist", id="savpl-title")
            yield Input(placeholder="Playlist name...", id="savpl-input")

    def on_mount(self):
        self.call_after_refresh(lambda: self.query_one("#savpl-input", Input).focus())

    def action_play_highlighted_next(self):
        """Queues the highlighted song right after the current one, ignoring checked items."""
        item = self._highlighted()
        if item:
            self.dismiss(("next", [item]))

    def action_confirm(self):
        name = self.query_one("#savpl-input", Input).value.strip()
        if name:
            self.dismiss(name)


# ─── Saved Playlists Screen ───────────────────────────────────────────────────

class SavedPlaylistsScreen(ModalScreen):
    CSS = """
    SavedPlaylistsScreen { align: center middle; }
    #sp-box {
        width: 80%; height: 70%;
        background: $surface;
        border: solid $accent;
        padding: 1 2;
    }
    #sp-title { text-style: bold; margin-bottom: 1; }
    #sp-hint  { color: $text-muted; margin-bottom: 1; }
    #sp-list  { height: 1fr; }
    """
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("enter",  "load",    "Load",   priority=True),
        Binding("d",      "delete",  "Delete"),
        Binding("delete", "delete",  "",       show=False),
    ]

    def __init__(self):
        super().__init__()
        self._playlists: list[Path] = []

    def compose(self) -> ComposeResult:
        with Container(id="sp-box"):
            yield Label("Saved Playlists", id="sp-title")
            yield Label("Enter: load  |  d: delete  |  Esc: close", id="sp-hint")
            yield ListView(id="sp-list")

    def on_mount(self):
        self._reload(keep_index=0)
        self.query_one("#sp-list", ListView).focus()

    def _reload(self, keep_index: int = 0):
        PLAYLISTS_DIR.mkdir(exist_ok=True)
        self._playlists = sorted(PLAYLISTS_DIR.glob("*.json"))
        lv = self.query_one("#sp-list", ListView)
        items = list(lv.query(ListItem))

        if not self._playlists:
            lv.clear()
            lv.append(ListItem(Label("  (no saved playlists)")))
        else:
            for i, p in enumerate(self._playlists):
                try:
                    data = json.loads(p.read_text())
                    name = data.get("name", p.stem)
                    count = len(data.get("songs", []))
                    text = f"  {name}  ({count} songs)"
                except Exception:
                    text = f"  {p.stem}"
                if i < len(items):
                    try:
                        items[i].query_one(Label).update(text)
                    except Exception:
                        pass
                else:
                    lv.append(ListItem(Label(text)))
            for item in items[len(self._playlists):]:
                item.remove()

            target = min(keep_index, len(self._playlists) - 1)

            def _restore():
                lv.focus()
                lv.index = target

            self.call_after_refresh(_restore)

        try:
            self.query_one("#sp-title", Label).update(
                f"Saved Playlists - {len(self._playlists)}" if self._playlists else "Saved Playlists"
            )
        except Exception:
            pass

    def action_load(self):
        lv = self.query_one("#sp-list", ListView)
        idx = lv.index
        if idx is None or not self._playlists or idx >= len(self._playlists):
            return
        try:
            data = json.loads(self._playlists[idx].read_text())
            songs = [Path(p) for p in data.get("songs", []) if Path(p).exists()]
            self.dismiss(songs)
        except Exception:
            self.dismiss([])

    def action_delete(self):
        lv = self.query_one("#sp-list", ListView)
        idx = lv.index
        if idx is None or not self._playlists or idx >= len(self._playlists):
            return
        self._playlists[idx].unlink(missing_ok=True)
        self._reload(keep_index=max(0, idx - 1))
