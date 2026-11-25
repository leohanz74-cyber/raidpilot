"""Wo auf dem Bildschirm was zu finden ist. Alle Werte relativ (0..1) bei 16:9 im Querformat."""
from . import store

# Name: (Bereich x0,y0,x1,y1, moegliche Beschriftungen Deutsch/Englisch)
BUTTONS = {
    "attack_home": ((0.00, 0.74, 0.20, 1.00), ("Attack!", "Attack", "Angriff!", "Angriff", "Angreifen")),
    "find_match": ((0.00, 0.35, 0.65, 0.98), ("Find a Match", "Find Match", "Gegner suchen", "Gegner finden", "Spiel suchen", "Find Now", "Jetzt suchen")),
    "army_attack": ((0.62, 0.72, 1.00, 1.00), ("Attack!", "Attack", "Angriff!", "Angreifen", "Angriff")),
    "next": ((0.76, 0.60, 1.00, 0.86), ("Next", "Weiter", "Nächster")),
    "end_battle": ((0.00, 0.60, 0.24, 0.86), ("End Battle", "Surrender", "Kampf beenden", "Aufgeben", "Beenden")),
    "return_home": ((0.30, 0.72, 0.70, 0.99), ("Return Home", "Zurück", "Heimkehren", "Nach Hause", "Zum Dorf")),
    "okay": ((0.18, 0.40, 0.82, 0.92), ("Okay", "OK")),
    "reload": ((0.18, 0.40, 0.82, 0.92), ("Reload", "Reload Game", "Try Again", "Neu laden", "Spiel neu laden", "Erneut versuchen", "Erneut verbinden")),
    "upgrade": ((0.15, 0.66, 0.85, 1.00), ("Upgrade", "Verbessern", "Ausbauen", "Aufwerten")),
    "confirm": ((0.25, 0.55, 0.95, 0.98), ("Confirm", "Bestätigen", "Okay", "Upgrade", "Verbessern", "Ausbauen")),
    "donate": ((0.00, 0.08, 0.45, 0.92), ("Donate", "Spenden")),
}
BUTTON_TITLES = {
    "attack_home": "Angriff (im Dorf)",
    "find_match": "Gegner suchen",
    "army_attack": "Angriff bestätigen",
    "next": "Weiter",
    "end_battle": "Kampf beenden / Aufgeben",
    "return_home": "Zurück zum Dorf",
    "okay": "Okay",
    "reload": "Neu laden",
    "upgrade": "Verbessern",
    "confirm": "Bestätigen",
    "donate": "Spenden",
}

REGIONS = {
    "loot": (0.00, 0.09, 0.22, 0.31),
    "home_storage": (0.76, 0.00, 1.00, 0.22),
    "result_loot": (0.30, 0.30, 0.70, 0.70),
    "troop_bar": (0.00, 0.81, 1.00, 1.00),
    "popup": (0.12, 0.12, 0.88, 0.92),
    "builder_list": (0.22, 0.08, 0.78, 0.92),
    "donate_popup": (0.20, 0.10, 0.95, 0.92),
}

POINTS = {
    "builder_menu": (0.455, 0.047),
    "chat_open": (0.012, 0.455),
    "chat_close": (0.385, 0.455),
}

# Absetz-Linien am Rand der Karte: (Start, Ende). In der Einrichtung anpassbar.
SIDES = {
    "tl": ((0.14, 0.45), (0.42, 0.11)),
    "tr": ((0.58, 0.11), (0.86, 0.45)),
    "bl": ((0.18, 0.56), (0.34, 0.75)),
    "br": ((0.82, 0.56), (0.66, 0.75)),
}
CENTER = (0.50, 0.43)

# Woerter, die auf einen Kauf hindeuten: dort wird nie bestaetigt
PURCHASE_WORDS = ("gem", "gems", "juwel", "juwelen", "buy", "kaufen", "missing", "fehlende", "notenough", "nichtgenug")
OTHER_DEVICE_WORDS = ("anotherdevice", "anderengerat", "anderesgerat", "anderemgerat")
BREAK_WORDS = ("personalbreak", "takeabreak", "pausemachen", "eigenepause", "zwangspause")
WALL_WORDS = ("wall", "mauer")

FILE = "layout.json"


def sides() -> dict:
    result = dict(SIDES)
    for key, line in store.load(FILE, {}).get("sides", {}).items():
        if key in result:
            try:
                (x1, y1), (x2, y2) = line
                result[key] = ((float(x1), float(y1)), (float(x2), float(y2)))
            except (TypeError, ValueError):
                pass
    return result


def set_side(key: str, start, end) -> None:
    if key not in SIDES:
        raise ValueError("Unbekannte Seite")
    clamp = lambda p: (min(0.99, max(0.01, float(p[0]))), min(0.80, max(0.02, float(p[1]))))
    data = store.load(FILE, {})
    data.setdefault("sides", {})[key] = [clamp(start), clamp(end)]
    store.save(FILE, data)


def reset_sides() -> None:
    data = store.load(FILE, {})
    data.pop("sides", None)
    store.save(FILE, data)
