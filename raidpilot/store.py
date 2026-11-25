"""Datenordner und sicheres Lesen/Schreiben von JSON."""
import json
import os
import sys
import threading
from pathlib import Path

_lock = threading.RLock()


def data_dir() -> Path:
    override = os.environ.get("RAIDPILOT_HOME")
    if override:
        root = Path(override)
    elif sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", str(Path.home()))) / "RaidPilot"
    else:
        root = Path.home() / ".raidpilot"
    root.mkdir(parents=True, exist_ok=True)
    return root


def load(name: str, default):
    path = data_dir() / name
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            # Kaputte Datei aufheben statt sie stillschweigend zu ueberschreiben
            try:
                os.replace(path, path.with_suffix(".defekt"))
            except OSError:
                pass
            return default
    return data if isinstance(data, type(default)) else default


def save(name: str, data) -> None:
    path = data_dir() / name
    tmp = path.with_suffix(".tmp")
    with _lock:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
