"""Truppenleiste erkennen und Absetz-Punkte planen."""
import math
import random
import re
from dataclasses import dataclass

import numpy as np

from . import layout, templates

COUNT_RE = re.compile(r"^[x×X]\s?([0-9OolIS]{1,3})$")
# Geometrie der Leiste relativ zur Bildhoehe (Fallback, wenn nur ein Zaehler sichtbar ist)
DEFAULT_STEP = 0.128


@dataclass
class Slot:
    index: int
    x: int
    y: int
    count: object = None      # None = Held o. ae. ohne Zaehler
    role: str = "troop"


def read_counts(screen) -> list:
    """Liste (x, y, anzahl) aller 'x12'-Zaehler in der Truppenleiste."""
    found = []
    for word in screen.words(layout.REGIONS["troop_bar"]):
        for part in re.finditer(r"[x×X]\s?[0-9OolIS]{1,3}(?![0-9])", word.text):
            number = COUNT_RE.match(part.group())
            if not number:
                continue
            digits = number.group(1).translate(str.maketrans("OolIS", "00115"))
            # Position innerhalb eines zusammengefassten Wortes schaetzen
            middle = (part.start() + part.end()) / 2 / max(1, len(word.text))
            found.append((int(word.x + word.w * middle), int(word.y + word.h / 2), int(digits)))
    return sorted(found)


def slot_step(counts, height: int) -> float:
    expected = DEFAULT_STEP * height
    gaps = [b[0] - a[0] for a, b in zip(counts, counts[1:])]
    candidates = []
    for gap in gaps:
        units = max(1, round(gap / expected))
        candidates.append(gap / units)
    usable = [c for c in candidates if 0.7 * expected <= c <= 1.35 * expected]
    return float(np.median(usable)) if usable else expected


def occupied(screen, x: int, count_y: int, step: float) -> bool:
    """Liegt an dieser Stelle eine Karte? Karten sind bunt, die leere Leiste ist gleichmaessig."""
    half = int(step * 0.32)
    top = count_y + int(step * 0.2)
    bottom = min(screen.height, count_y + int(step * 0.85))
    patch = screen.image[top:bottom, max(0, x - half):min(screen.width, x + half)]
    if patch.size == 0:
        return False
    return float(patch.reshape(-1, 3).std(axis=0).mean()) > 22


def detect_slots(screen) -> list:
    counts = read_counts(screen)
    if not counts:
        return []
    step = slot_step(counts, screen.height)
    count_y = int(np.median([c[1] for c in counts]))
    first = counts[0][0]
    # Auch links vom ersten Zaehler nach Karten schauen
    start = first
    while start - step > step * 0.4 and occupied(screen, int(start - step), count_y, step):
        start -= step
    slots = []
    position = start
    empty = 0
    while position < screen.width - step * 0.3 and len(slots) < 14 and empty < 2:
        near = [c for c in counts if abs(c[0] - position) < step * 0.45]
        x = near[0][0] if near else int(position)
        if near or occupied(screen, x, count_y, step):
            card_y = min(screen.height - 2, count_y + int(step * 0.5))
            slots.append(Slot(len(slots), x, card_y, near[0][2] if near else None))
            position = x + step
            empty = 0
        else:
            position += step
            empty += 1
    return slots


def assign_roles(screen, slots: list, settings: dict) -> list:
    """Rollen festlegen: erfasste Truppen, feste Vorgaben, sonst Reihenfolge der Leiste."""
    has_hero = any(s.count is None for s in slots)
    first_hero = next((s.index for s in slots if s.count is None), len(slots))
    spell_tail = 0 if settings["spell"] == "none" else settings["spell_slots"]
    for slot in slots:
        if slot.count is None:
            slot.role = "hero"
        elif has_hero:
            slot.role = "spell" if slot.index > first_hero else "troop"
        else:
            slot.role = "spell" if slot.index >= len(slots) - spell_tail and len(slots) > spell_tail else "troop"
    # Eine einzelne Karte direkt vor den Helden ist fast immer die Belagerungsmaschine
    if has_hero and first_hero >= 2 and slots[first_hero - 1].count == 1:
        slots[first_hero - 1].role = "siege"

    wanted = settings["army"]
    half = int(slot_step([(s.x, s.y, 0) for s in slots], screen.height) * 0.6)
    own, events = set(), set()
    for entry in templates.index():
        if entry["kind"] not in ("troop", "event"):
            continue
        image = templates.load_image(entry, screen.width)
        for slot in slots:
            region = (max(0, slot.x - half) / screen.width, layout.REGIONS["troop_bar"][1],
                      min(screen.width, slot.x + half) / screen.width, 1.0)
            if screen.match_template(image, region, threshold=0.82):
                if entry["kind"] == "event":
                    events.add(slot.index)
                elif wanted == "custom" or normalize_army(entry["name"]) == wanted:
                    own.add(slot.index)
    # Wenn passende Truppen erfasst sind, nur diese als normale Truppen einsetzen
    if own or wanted == "custom":
        for slot in slots:
            if slot.role == "troop" and slot.index not in own:
                slot.role = "skip"
            elif slot.index in own:
                slot.role = "troop"
    for index in events:
        slots[index].role = "event"
    for slot in slots:
        manual = settings["slot_roles"][slot.index] if slot.index < len(settings["slot_roles"]) else "auto"
        if manual != "auto":
            slot.role = manual
    return slots


def normalize_army(name: str) -> str:
    text = name.lower()
    if "elektro" in text or "electro" in text or "e-drag" in text:
        return "edrag"
    if "drach" in text or "dragon" in text:
        return "dragon"
    if "kobold" in text or "goblin" in text:
        return "goblin"
    if "barbar" in text or "bogen" in text or "archer" in text:
        return "barch"
    return text


def choose_sides(style: str, army: str, rng=random) -> list:
    if style == "random":
        style = rng.choice(["tl", "tr", "bl", "br"])
        # Kobolde und Barbaren verteilen sich besser ueber zwei Seiten
        if army == "goblin":
            return ["tl", "br"] if style in ("tl", "br") else ["tr", "bl"]
    if style == "top":
        return ["tl", "tr"]
    if style == "all":
        return ["tl", "tr", "br", "bl"]
    return [style]


def line_points(sides: dict, names: list, count: int, outward: float = 0.0) -> list:
    """count Punkte gleichmaessig ueber die gewaehlten Seiten (relative Koordinaten)."""
    count = max(1, count)
    points = []
    per_side = [count // len(names) + (1 if i < count % len(names) else 0) for i in range(len(names))]
    for name, amount in zip(names, per_side):
        (x1, y1), (x2, y2) = sides[name]
        for i in range(amount):
            t = 0.5 if amount == 1 else i / (amount - 1)
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            if outward:
                dx, dy = x - layout.CENTER[0], y - layout.CENTER[1]
                length = math.hypot(dx, dy) or 1
                x += dx / length * outward
                y += dy / length * outward
            points.append((min(0.985, max(0.015, x)), min(0.79, max(0.03, y))))
    return points


def spell_points(sides: dict, names: list, count: int, depth: float = 0.55) -> list:
    """Zauber auf dem Weg von der Absetzseite zur Mitte."""
    edge = line_points(sides, names, count)
    return [(x + (layout.CENTER[0] - x) * depth, y + (layout.CENTER[1] - y) * depth) for x, y in edge]
