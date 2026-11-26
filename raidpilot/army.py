"""Troop bar recognition and deployment planning."""
import math
import random
import re
from dataclasses import dataclass

import cv2
import numpy as np

from . import layout, templates

COUNT_RE = re.compile(r"[x×X]\s?([0-9OolIS]{1,3})(?![0-9])")
_DIGITS = str.maketrans("OolIS", "00115")


@dataclass
class Slot:
    index: int
    x: int                    # centre of the card
    y: int
    left: int
    right: int
    count: object = None      # None = card without counter (hero)
    role: str = "troop"       # troop, event, siege, hero, spell


def find_cards(image) -> list:
    """(left, right) of every troop card. Cards are bright, empty places in the bar are dim."""
    height, width = image.shape[:2]
    strip = image[int(.836 * height):int(.972 * height)]
    value = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)[:, :, 2]
    bright = np.percentile(value, 80, axis=0) > 118
    runs, start = [], None
    for x, on in enumerate(np.append(bright, False)):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if runs and start - runs[-1][1] <= 0.003 * width:
                runs[-1][1] = x
            else:
                runs.append([start, x])
            start = None
    typical = 0.068 * width
    cards = []
    for left, right in runs:
        span = right - left
        if span < 0.045 * width:
            continue
        parts = max(1, round(span / (typical * 1.06)))
        cards.extend((int(left + span * i / parts), int(left + span * (i + 1) / parts)) for i in range(parts))
    return cards[:14]


def read_counts(screen) -> list:
    """(x, count) of every 'x12' counter in the troop bar."""
    found = []
    for word in screen.words(layout.REGIONS["troop_bar"]):
        for match in COUNT_RE.finditer(word.text):
            digits = match.group(1).translate(_DIGITS)
            # The counter sits at the right end of what was read as one word
            share = (match.start() + match.end()) / 2 / max(1, len(word.text))
            found.append((int(word.x + word.w * share), int(digits)))
    return sorted(found)


def header_count(screen, left: int, right: int):
    """Reads the counter of one card on its own, enlarged. None if the card has none."""
    height = screen.height
    crop = screen.image[int(.822 * height):int(.874 * height), max(0, left):right]
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    for word in screen.ocr.read(crop):
        match = COUNT_RE.search(word.text)
        if match:
            return int(match.group(1).translate(_DIGITS))
    return None


def card_count(screen, left: int, right: int):
    """Counter of the card between left and right, or None."""
    inside = [count for x, count in read_counts(screen) if left - 4 <= x <= right + 4]
    return inside[-1] if inside else header_count(screen, left, right)


def _share(patch, low, high) -> float:
    if patch.size == 0:
        return 0.0
    return float(cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV), low, high).mean()) / 255


def has_event_badge(image, left: int, right: int) -> bool:
    """Event troops carry a small beige box at the top left of their card."""
    height = image.shape[0]
    width = right - left
    patch = image[int(.832 * height):int(.865 * height), left + int(width * .07):left + int(width * .33)]
    return _share(patch, (8, 15, 150), (30, 200, 255)) > 0.30


def is_purple(image, left: int, right: int) -> bool:
    """Purple card art (rage spell)."""
    height = image.shape[0]
    width = right - left
    patch = image[int(.875 * height):int(.965 * height), left + int(width * .2):right - int(width * .2)]
    return _share(patch, (126, 90, 90), (162, 255, 255)) > 0.18


def detect_slots(screen) -> list:
    cards = find_cards(screen.image)
    if not cards:
        return []
    return [Slot(index, (left + right) // 2, int(.905 * screen.height), left, right,
                 card_count(screen, left, right))
            for index, (left, right) in enumerate(cards)]


def assign_roles(screen, slots: list) -> list:
    """Order of the bar: troops, siege machine, heroes, spells."""
    first_hero = next((s.index for s in slots if s.count is None), None)
    entries = [(entry, templates.load_image(entry, screen.width)) for entry in templates.index()]
    # Cards separated by a wider gap form groups
    group, previous = 0, None
    groups = []
    for slot in slots:
        if previous is not None and slot.left - previous > 0.012 * screen.width:
            group += 1
        groups.append(group)
        previous = slot.right
    for slot in slots:
        if slot.count is None:
            slot.role = "hero"
            continue
        event = has_event_badge(screen.image, slot.left, slot.right) or \
            any(templates.matches(screen.image, image, slot.left, slot.right) for _, image in entries)
        if first_hero is not None and slot.index > first_hero:
            slot.role = "spell"
        elif event:
            slot.role = "event"
        elif first_hero is None and group > 0 and groups[slot.index] == group:
            slot.role = "spell"
        else:
            slot.role = "troop"
    if first_hero is not None and first_hero >= 2:
        before = slots[first_hero - 1]
        if before.count == 1 and before.role == "troop":
            before.role = "siege"
    return slots


def choose_spells(image, slots: list, wanted: str) -> list:
    """The spell cards to use for the selected spell type."""
    spells = [s for s in slots if s.role == "spell" and s.count]
    if wanted == "none" or not spells:
        return []
    purple = [s for s in spells if is_purple(image, s.left, s.right)]
    if wanted == "rage":
        return purple or spells
    return [s for s in spells if s not in purple] or spells


def choose_sides(style: str, army: str, rng=random) -> list:
    if style == "all":
        return ["tl", "tr", "br", "bl"]
    if style == "random":
        # Goblins loot best when they come from everywhere
        if army == "sneaky_goblin":
            return ["tl", "tr", "br", "bl"]
        return [rng.choice(["tl", "tr", "bl", "br"])]
    return [style]


def line_span(army: str) -> tuple:
    """Which part of a side is used. Ground smash armies stay close together."""
    if army in ("valkyrie", "meteor_golem"):
        return (0.25, 0.75)
    return (0.0, 1.0)


def _inside(x: float, y: float) -> tuple:
    """Moves a point towards the middle of the map until it is not on a button."""
    x = min(0.985, max(0.015, x))
    y = min(0.79, max(0.03, y))
    for _ in range(20):
        if not layout.blocked(x, y):
            break
        x += (layout.CENTER[0] - x) * 0.08
        y += (layout.CENTER[1] - y) * 0.08
    return (x, y)


def line_points(names: list, count: int, outward: float = 0.0, span=(0.0, 1.0)) -> list:
    """count points spread evenly over the chosen sides (relative coordinates)."""
    count = max(1, count)
    points = []
    per_side = [count // len(names) + (1 if i < count % len(names) else 0) for i in range(len(names))]
    for name, amount in zip(names, per_side):
        (x1, y1), (x2, y2) = layout.SIDES[name]
        for i in range(amount):
            t = 0.5 if amount == 1 else span[0] + (span[1] - span[0]) * i / (amount - 1)
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            if outward:
                dx, dy = x - layout.CENTER[0], y - layout.CENTER[1]
                length = math.hypot(dx, dy) or 1
                x += dx / length * outward
                y += dy / length * outward
            points.append(_inside(x, y))
    return points


def spell_points(names: list, count: int) -> list:
    """Spells go on the way from the deployment side to the middle, first near, then deeper."""
    first = (count + 1) // 2
    points = []
    for amount, depth in ((first, 0.38), (count - first, 0.62)):
        if amount:
            for x, y in line_points(names, amount, span=(0.2, 0.8)):
                points.append((x + (layout.CENTER[0] - x) * depth, y + (layout.CENTER[1] - y) * depth))
    return points
