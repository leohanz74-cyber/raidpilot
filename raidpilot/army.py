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


def edge_share(image):
    """For every column of the troop bar: over how much of its height there is a sharp edge."""
    height, width = image.shape[:2]
    strip = image[int(.838 * height):int(.968 * height)].astype(np.int16)
    step = max(1, round(width / 800))
    jump = np.abs(strip[:, 2 * step:] - strip[:, :-2 * step]).max(axis=2)
    share = np.zeros(width)
    share[step:-step] = (jump > 22).mean(axis=0)
    return share


def card_edges(share) -> list:
    """Neighbouring columns with an edge over (almost) the whole height, as [first, last]."""
    edges = []
    for x in np.flatnonzero(share > 0.8):
        if edges and x - edges[-1][1] <= 3:
            edges[-1][1] = int(x)
        else:
            edges.append([int(x), int(x)])
    return edges


def cards_between_edges(share, edges: list, bright) -> list:
    """Cards found by their outlines: two edges one card width apart with a bright inside."""
    width = len(share)
    low, typical, high = (int(v * width) for v in (0.064, 0.069, 0.073))
    columns = [x for first, last in edges for x in range(first, last + 1)]
    pairs = [(left, right) for left in columns for right in columns if low <= right - left <= high]
    # The clearest outlines first, then the width that fits best
    pairs.sort(key=lambda p: (-round(float(share[p[0]] + share[p[1]]) * 20), abs(p[1] - p[0] - typical)))
    cards = []
    for left, right in pairs:
        overlaps = any(left < other[1] - 3 and right > other[0] + 3 for other in cards)
        if not overlaps and bright[left + 6:right - 6].mean() > 0.7:
            cards.append((left, right))
    return sorted(cards)


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
    runs = [run for run in runs if run[1] - run[0] >= 0.045 * width]
    # Over a bright village the background shines through the bar and merges with the cards:
    # then a bright stretch does not begin and end at the outline of a card, and the outlines decide.
    share = edge_share(image)
    edges = card_edges(share)
    reach = 0.006 * width
    outline = lambda x: any(first - reach <= x <= last + reach for first, last in edges)
    if not all(outline(left) and outline(right) for left, right in runs):
        outlined = cards_between_edges(share, edges, bright)
        if outlined:
            return outlined[:14]
    typical = 0.068 * width
    cards = []
    for left, right in runs:
        span = right - left
        parts = max(1, round(span / (typical * 1.06)))
        cards.extend((int(left + span * i / parts), int(left + span * (i + 1) / parts)) for i in range(parts))
    return cards[:14]


def _parse_count(text: str):
    match = COUNT_RE.search(text)
    return int(match.group(1).translate(_DIGITS)) if match else None


def card_count(screen, left: int, right: int):
    """Counter ('x12') of the card between left and right, or None if the card has none."""
    height = screen.height
    width = right - left
    left = max(0, left)
    # First the whole head of the card, then only its right part where the counter ends
    for y0, y1, x0 in ((0.822, 0.874, left), (0.831, 0.865, left + int(width * 0.23))):
        crop = screen.image[int(y0 * height):int(y1 * height), x0:right]
        text, score = screen.ocr.line(crop)
        count = _parse_count(text) if score >= 0.4 else None
        if count is not None:
            return count
    # Slower, but finds counters the quick way misses
    crop = screen.image[int(.822 * height):int(.874 * height), left:right]
    if crop.size == 0:
        return None
    for word in screen.ocr.read(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)):
        count = _parse_count(word.text)
        if count is not None:
            return count
    return None


def hero_deployed(image, left: int, right: int) -> bool:
    """True once the hero is on the field: grey card art, or a green health bar above the card."""
    height = image.shape[0]
    art = image[int(layout.HERO_ART[0] * height):int(layout.HERO_ART[1] * height), left + 12:right - 12]
    if art.size and float(cv2.cvtColor(art, cv2.COLOR_BGR2HSV)[:, :, 1].mean()) < 40:
        return True
    top, bottom = (int(v * height) for v in layout.HERO_BAR)
    strip = image[top:bottom, left + 10:right - 10]
    if strip.size == 0:
        return False
    # Pure green, unlike grass; a bar fills most of the width for several rows
    green = cv2.inRange(cv2.cvtColor(strip, cv2.COLOR_BGR2HSV), (40, 190, 140), (75, 255, 255))
    return int(((green.mean(axis=1) / 255) > 0.5).sum()) >= 5


def is_warden(image, left: int, right: int) -> bool:
    """Recognises the Grand Warden on a waiting (colourful) card: purple art or the ground/air switch."""
    height = image.shape[0]
    width = right - left
    switch = image[int(layout.WARDEN_SWITCH[0] * height):int(layout.WARDEN_SWITCH[1] * height),
                   left + int(width * 0.55):right - int(width * 0.08)]
    if _share(switch, (35, 90, 130), (80, 255, 255)) > 0.35:
        return True
    art = image[int(0.850 * height):int(0.978 * height), left + 6:right - 6]
    return _share(art, (135, 90, 60), (165, 255, 255)) > 0.28


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


def choose_sides(style: str, army: str, rng=random, loot_side: str | None = None) -> list:
    """The edges to deploy on. loot_side: the edge with the most storages, for the style "loot"."""
    if style == "loot":
        if loot_side:
            return [loot_side]
        style = "random"  # nothing recognised
    if style == "all":
        return ["tl", "tr", "br", "bl"]
    if style == "random":
        # Goblins loot best when they come from everywhere
        if army == "sneaky_goblin":
            return ["tl", "tr", "br", "bl"]
        # Only the upper sides: the troop bar hides part of the lower ones, troops would bunch up there
        return [rng.choice(["tl", "tr"])]
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


def spot(name: str, t: float, outward: float = 0.0) -> tuple:
    """The point at share t (0..1) of a side, moved away from the middle by outward."""
    (x1, y1), (x2, y2) = layout.SIDES[name]
    x = x1 + (x2 - x1) * t
    y = y1 + (y2 - y1) * t
    if outward:
        dx, dy = x - layout.CENTER[0], y - layout.CENTER[1]
        length = math.hypot(dx, dy) or 1
        x += dx / length * outward
        y += dy / length * outward
    return _inside(x, y)


def line_points(names: list, count: int, outward: float = 0.0, span=(0.0, 1.0)) -> list:
    """count points spread evenly over the chosen sides (relative coordinates)."""
    count = max(1, count)
    points = []
    per_side = [count // len(names) + (1 if i < count % len(names) else 0) for i in range(len(names))]
    for name, amount in zip(names, per_side):
        for i in range(amount):
            t = 0.5 if amount == 1 else span[0] + (span[1] - span[0]) * i / (amount - 1)
            points.append(spot(name, t, outward))
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
