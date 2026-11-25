"""Selbst erfasste Bildausschnitte (Knoepfe oder Truppen-Symbole)."""
import re
import time

import cv2

from . import store

FILE = "templates.json"
KINDS = ("button", "troop", "event")


def folder():
    path = store.data_dir() / "templates"
    path.mkdir(exist_ok=True)
    return path


def index() -> list:
    return store.load(FILE, [])


def add(kind: str, name: str, frame, rect) -> dict:
    """rect = (x0, y0, x1, y1) relativ zum Bild."""
    if kind not in KINDS:
        raise ValueError("Unbekannte Art")
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in rect)
    x0, x1 = sorted((int(x0 * width), int(x1 * width)))
    y0, y1 = sorted((int(y0 * height), int(y1 * height)))
    if x1 - x0 < 12 or y1 - y0 < 12:
        raise ValueError("Der Ausschnitt ist zu klein.")
    name = str(name).strip()[:30] or "Truppe"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "vorlage"
    filename = f"{kind}-{slug}-{int(time.time() * 1000)}.png"
    ok, data = cv2.imencode(".png", frame[y0:y1, x0:x1])
    if not ok:
        raise ValueError("Ausschnitt konnte nicht gespeichert werden.")
    (folder() / filename).write_bytes(data.tobytes())
    entry = {"kind": kind, "name": name, "file": filename, "screen_width": width}
    entries = index()
    if kind == "button":
        for old in [e for e in entries if e["kind"] == "button" and e["name"] == name]:
            (folder() / old["file"]).unlink(missing_ok=True)
            entries.remove(old)
    entries.append(entry)
    store.save(FILE, entries)
    return entry


def remove(filename: str) -> None:
    entries = index()
    for entry in [e for e in entries if e["file"] == filename]:
        (folder() / entry["file"]).unlink(missing_ok=True)
        entries.remove(entry)
    store.save(FILE, entries)


def load_image(entry: dict, screen_width: int):
    path = folder() / entry["file"]
    try:
        import numpy as np

        image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None
    if image is None:
        return None
    scale = screen_width / max(1, entry.get("screen_width", screen_width))
    if abs(scale - 1) > 0.01:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image
