import json
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
from utils import song_label, yt_search


# ─── Recommended Prompt ───────────────────────────────────────────────────────

class RecommendedPrompt(ModalScreen):
    CSS = """
    RecommendedPrompt { align: center middle; }
    #rp-box {
        width: 70; height: 13;
        background: $surface;
        border: solid $accent;
        padding: 2 4;
        align: center middle;
    }
    #rp-title  { text-align: center; text-style: bold; margin-bottom: 2; }
    #rp-opts   { width: 100%; height: 3; align: center middle; }
    .rp-btn    { width: 20; height: 3; border: solid $panel; content-align: center middle; margin: 0 1; }
    .rp-active { border: solid $accent; color: $accent; text-style: bold; }
    """
    BINDINGS = [
        Binding("left",   "pick_yes",  "", show=False),
        Binding("right",  "pick_no",   "", show=False),
        Binding("y",      "pick_yes",  "", show=False),
        Binding("n",      "pick_no",   "", show=False),
        Binding("enter",  "confirm",   "Confirm"),
        Binding("escape", "cancel",    "Cancel"),
    ]

    _choice: reactive[bool] = reactive(True)

    def compose(self) -> ComposeResult:
        with Container(id="rp-box"):
            yield Label("Start downloading\nrecommended songs?", id="rp-title")
            with Horizontal(id="rp-opts"):
                yield Static("  ✔  Yes  ", id="rp-yes", classes="rp-btn rp-active")
                yield Static("  ✘  No   ", id="rp-no",  classes="rp-btn")

    def watch__choice(self, val: bool):
        try:
            yes = self.query_one("#rp-yes", Static)
            no  = self.query_one("#rp-no",  Static)
            if val:
                yes.add_class("rp-active")
                no.remove_class("rp-active")
            else:
                no.add_class("rp-active")
                yes.remove_class("rp-active")
        except Exception:
            pass

    def action_pick_yes(self):
        self._choice = True

    def action_pick_no(self):
        self._choice = False

    def action_confirm(self):
        self.dismiss(self._choice)

    def action_cancel(self):
        self.dismiss(False)


# ─── Search Screen ────────────────────────────────────────────────────────────

class SearchScreen(ModalScreen):
    """Ctrl+F — local + YouTube search, Space to check items"""

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
    .local-item { color: $text; }
    .yt-item    { color: $warning; }
    """

    BINDINGS = [
        Binding("enter",      "close",      "Add to queue", priority=True),
        Binding("ctrl+space", "play_next",  "Play Next"),
        Binding("escape",     "dismiss",    "Close"),
        Binding("tab",        "focus_list", "List"),
    ]

    def __init__(self, local: List[SearchResult]):
        super().__init__()
        self._local = local
        self._results: List[SearchResult] = list(local)
        self._checked: set[SearchResult] = set()
        self._current_query = ""

    def compose(self) -> ComposeResult:
        with Container(id="sb-box"):
            yield Label("Search  (local + YouTube)", id="sb-title")
            yield Label(
                "↑↓: navigate  |  Space: check  |  Enter: play highlighted / add checked  |  Ctrl+Space: play next  |  Esc: close",
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
        import time
        time.sleep(0.4)
        if self._current_query != query:
            return
        results = yt_search(query)
        self.app.call_from_thread(self._add_yt_results, results)

    def _add_yt_results(self, yt: List[SearchResult]):
        local_labels = {r.display for r in self._results}
        new = [r for r in yt if r.display not in local_labels]
        self._results = self._results + new
        count = len(new)
        self._set_status(f"Found {count} YouTube results" if count else "No new YT results")
        self._refresh_list()

    def _set_status(self, text: str):
        try:
            self.query_one("#sb-status", Static).update(text)
        except Exception:
            pass

    def _refresh_list(self, keep_index: Optional[int] = None):
        lv = self.query_one("#sb-list", ListView)
        lv.clear()
        for r in self._results[:200]:
            mark = "☑" if r in self._checked else "☐"
            lv.append(ListItem(Label(f"  {mark}  {r.display}")))
        if keep_index is not None:
            self.call_after_refresh(lambda: setattr(lv, "index", keep_index))

    def _toggle_at(self, idx: int):
        if idx < len(self._results):
            r = self._results[idx]
            if r in self._checked:
                self._checked.discard(r)
            else:
                self._checked.add(r)
            self._refresh_list(keep_index=idx)

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

    def action_play_next(self):
        self.dismiss(("next", list(self._checked)) if self._checked else None)

    def action_close(self):
        if self._checked:
            self.dismiss(("queue", list(self._checked)))
            return
        lv = self.query_one("#sb-list", ListView)
        if lv.has_focus and lv.index is not None and lv.index < len(self._results):
            self.dismiss(("play_now", [self._results[lv.index]]))
        else:
            self.dismiss(None)


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
        Binding("ctrl+d",    "delete_all",    "Delete all"),
    ]

    def __init__(self, playlist: PlaylistManager):
        super().__init__()
        self._playlist = playlist

    def compose(self) -> ComposeResult:
        songs = self._playlist.all_upcoming()
        with Container(id="pl-box"):
            yield Label(f"Playlist — {len(songs)} songs in queue", id="pl-title")
            yield Label(
                "↑↓: navigate  |  Ctrl+↑↓: reorder  |  d: delete  |  Ctrl+D: clear all  |  Esc: close",
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
                f"Playlist — {len(songs)} songs in queue"
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

    def action_play_selected(self):
        lv = self.query_one("#pl-list", ListView)
        idx = lv.index
        if idx is not None:
            self.dismiss(("play", idx))

    def action_delete_all(self):
        while self._playlist.all_upcoming():
            self._playlist.remove(0)
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
            yield Label(f"Library — {len(self._all)} songs", id="lib-title")
            yield Label(
                "↑↓: navigate  |  Space: add to end / remove  |  Ctrl+Space: add to front / remove  |  Esc: close",
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
                label = Label(f"  ☑  [{pos:>3}]  {r.display}", classes="in-queue")
            else:
                label = Label(f"  ☐         {r.display}")
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
                f"Saved Playlists — {len(self._playlists)}" if self._playlists else "Saved Playlists"
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
