"""Log im Speicher (fuer die Oberflaeche) und als Datei."""
import threading
import time
from collections import deque

from . import store

MAX_FILE = 1_000_000


class Log:
    def __init__(self, to_file: bool = True):
        self._lock = threading.Lock()
        self._lines = deque(maxlen=600)
        self._next = 1
        self.to_file = to_file
        self.generation = 0

    def __call__(self, text: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        with self._lock:
            self._lines.append({"id": self._next, "time": stamp, "level": level, "text": str(text)})
            self._next += 1
            if self.to_file:
                try:
                    path = store.data_dir() / "raidpilot.log"
                    if path.exists() and path.stat().st_size > MAX_FILE:
                        path.replace(path.with_suffix(".alt.log"))
                    with open(path, "a", encoding="utf-8") as fh:
                        fh.write(f"{time.strftime('%Y-%m-%d')} {stamp} [{level}] {text}\n")
                except OSError:
                    pass

    def since(self, last_id: int = 0) -> list:
        with self._lock:
            return [line for line in self._lines if line["id"] > last_id]

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self.generation += 1
