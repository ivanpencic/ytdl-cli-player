import os
import signal
import subprocess
import threading
from typing import Callable, Optional


class AudioPlayer:
    def __init__(self, on_end: Callable):
        self._proc: Optional[subprocess.Popen] = None
        self._on_end = on_end
        self._lock = threading.Lock()
        self._paused = False

    def play(self, path: str):
        self.stop()
        with self._lock:
            proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._proc = proc
        # Pass proc explicitly: reading self._proc in the thread could pick up a
        # newer process and fire on_end twice for it.
        threading.Thread(target=self._wait, args=(proc,), daemon=True).start()

    def _wait(self, proc: subprocess.Popen):
        proc.wait()
        if proc.returncode == 0:
            self._on_end()

    def pause(self):
        with self._lock:
            if self._proc and not self._paused and self._proc.poll() is None:
                os.kill(self._proc.pid, signal.SIGSTOP)
                self._paused = True

    def resume(self):
        with self._lock:
            if self._proc and self._paused and self._proc.poll() is None:
                os.kill(self._proc.pid, signal.SIGCONT)
                self._paused = False

    def toggle_pause(self):
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                return
            if self._paused:
                os.kill(self._proc.pid, signal.SIGCONT)
                self._paused = False
            else:
                os.kill(self._proc.pid, signal.SIGSTOP)
                self._paused = True

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self):
        with self._lock:
            if self._proc:
                if self._paused:
                    os.kill(self._proc.pid, signal.SIGCONT)
                    self._paused = False
                self._proc.terminate()
                self._proc = None
