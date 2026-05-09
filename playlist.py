import threading
from pathlib import Path
from typing import List, Optional


class PlaylistManager:
    def __init__(self):
        self._queue: List[Path] = []
        self._current: int = -1
        self._lock = threading.Lock()

    def add(self, path: Path):
        with self._lock:
            self._queue.append(path)

    def add_next(self, path: Path):
        with self._lock:
            self._queue.insert(self._current + 1, path)

    def advance(self) -> Optional[Path]:
        with self._lock:
            self._current += 1
            if self._current < len(self._queue):
                return self._queue[self._current]
            return None

    @property
    def current(self) -> Optional[Path]:
        with self._lock:
            if 0 <= self._current < len(self._queue):
                return self._queue[self._current]
            return None

    def upcoming(self, n: int = 5) -> List[Path]:
        with self._lock:
            s = self._current + 1
            return list(self._queue[s:s + n])

    def all_upcoming(self) -> List[Path]:
        with self._lock:
            return list(self._queue[self._current + 1:])

    def move_up(self, idx: int):
        with self._lock:
            real = self._current + 1 + idx
            if real > self._current + 1:
                self._queue[real], self._queue[real - 1] = (
                    self._queue[real - 1], self._queue[real]
                )

    def move_down(self, idx: int):
        with self._lock:
            real = self._current + 1 + idx
            if real < len(self._queue) - 1:
                self._queue[real], self._queue[real + 1] = (
                    self._queue[real + 1], self._queue[real]
                )

    def remove(self, idx: int):
        with self._lock:
            real = self._current + 1 + idx
            if 0 <= real < len(self._queue):
                del self._queue[real]

    def replace_next(self, path: Path):
        """Replaces the first upcoming song with path, or inserts it if nothing is queued ahead."""
        with self._lock:
            next_idx = self._current + 1
            if next_idx < len(self._queue):
                self._queue[next_idx] = path
            else:
                self._queue.insert(next_idx, path)

    def remove_path(self, path: Path):
        """Removes the first occurrence of path from the upcoming queue."""
        with self._lock:
            start = self._current + 1
            for i in range(start, len(self._queue)):
                if self._queue[i] == path:
                    del self._queue[i]
                    return

    def clear_upcoming(self):
        """Removes all upcoming (not-yet-played) songs from the queue."""
        with self._lock:
            del self._queue[self._current + 1:]

    def jump_to_upcoming(self, idx: int):
        """Advances current pointer so that upcoming[idx] is played next."""
        with self._lock:
            self._current += idx

    def total(self) -> int:
        with self._lock:
            return len(self._queue)
