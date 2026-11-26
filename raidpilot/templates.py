"""Event troop icons captured by the user."""
import time

import cv2
import numpy as np

from . import store

FILE = "event_troops.json"
# Size of the captured square, relative to the screen width
CROP = 0.034
THRESHOLD = 0.80


def folder():
    path = store.data_dir() / "event_troops"
    path.mkdir(exist_ok=True)
    return path


def index() -> list:
    return store.load(FILE, [])


def add(frame, x: float, y: float) -> dict:
    """x, y: relative position of the icon centre on the picture."""
    height, width = frame.shape[:2]
    half = int(CROP * width / 2)
    cx = min(width - half, max(half, int(float(x) * width)))
    cy = min(height - half, max(half, int(float(y) * height)))
    crop = frame[cy - half:cy + half, cx - half:cx + half]
    if crop.size == 0 or float(crop.std()) < 8:
        raise ValueError("There is no icon at this position.")
    filename = f"event-{int(time.time() * 1000)}.png"
    ok, data = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("The icon could not be saved.")
    (folder() / filename).write_bytes(data.tobytes())
    entry = {"file": filename, "screen_width": width}
    store.save(FILE, index() + [entry])
    return entry


def clear() -> None:
    for entry in index():
        (folder() / entry["file"]).unlink(missing_ok=True)
    store.save(FILE, [])


def load_image(entry: dict, screen_width: int):
    try:
        raw = (folder() / entry["file"]).read_bytes()
    except OSError:
        return None
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    scale = screen_width / max(1, entry.get("screen_width", screen_width))
    if abs(scale - 1) > 0.01:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image


def matches(frame, icon, left: int, right: int) -> bool:
    """Is the icon on this card? The card art may be drawn at another size than where it was captured."""
    if icon is None:
        return False
    height = frame.shape[0]
    card = frame[int(.82 * height):int(.99 * height), max(0, left):right]
    for scale in (0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0):
        resized = cv2.resize(icon, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if resized.shape[0] > card.shape[0] or resized.shape[1] > card.shape[1] or min(resized.shape[:2]) < 16:
            continue
        if cv2.minMaxLoc(cv2.matchTemplate(card, resized, cv2.TM_CCOEFF_NORMED))[1] >= THRESHOLD:
            return True
    return False
