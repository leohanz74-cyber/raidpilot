"""Statistik: aktuelle Sitzung und Gesamtwerte je Profil."""
import threading
import time

from . import store

FIELDS = ("gold", "elixir", "dark", "attacks", "walls", "searches", "runtime")
FILE = "stats.json"


class Stats:
    def __init__(self, user: str = "default"):
        self._lock = threading.RLock()
        self.user = user.casefold()
        self.session = dict.fromkeys(FIELDS, 0)
        self._started = None
        self._counted = 0.0

    def start(self) -> None:
        with self._lock:
            self.session = dict.fromkeys(FIELDS, 0)
            self._started = time.monotonic()
            self._counted = 0.0

    def stop(self) -> None:
        with self._lock:
            self._save_runtime()
            self._started = None

    def add(self, **values) -> None:
        with self._lock:
            data = store.load(FILE, {})
            total = data.setdefault(self.user, {})
            for key, amount in values.items():
                if key not in FIELDS or not amount:
                    continue
                self.session[key] += amount
                total[key] = total.get(key, 0) + amount
            store.save(FILE, data)

    def _pending(self) -> int:
        """Laufzeit, die noch nicht gespeichert ist."""
        if self._started is None:
            return 0
        return max(0, int(time.monotonic() - self._started - self._counted))

    def _save_runtime(self) -> None:
        pending = self._pending()
        if pending:
            self._counted += pending
            self.add(runtime=pending)

    def snapshot(self) -> dict:
        with self._lock:
            if self._pending() >= 30:  # nicht bei jeder Abfrage auf die Platte schreiben
                self._save_runtime()
            result = dict(self.session)
            result["runtime"] += self._pending()
            return result

    def lifetime(self) -> dict:
        total = store.load(FILE, {}).get(self.user, {})
        return {key: total.get(key, 0) for key in FIELDS}
