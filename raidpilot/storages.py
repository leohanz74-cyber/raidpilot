"""Finds the gold and elixir storages on an opponent base and picks the side of the map that is
closest to them. The storages are recognised by a small network (storages.onnx, a few hundred kB)
that was trained on screenshots of opponent bases at the fully zoomed out view."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import layout

MODEL = Path(__file__).with_name("storages.onnx")
KINDS = {1: "elixir", 2: "gold"}
# The network looks at windows of 46x46 pixels of the half-size picture and moves 8 pixels per step.
# Four slightly shifted passes give a step of 4 pixels.
HALF = (800, 450)
WINDOW = 46
STRIDE = 8
SHIFTS = ((0, 0), (4, 4), (4, 0), (0, 4))
THRESHOLD = 0.8
SPACING = 52          # pixels at 1600x900: closer hits are the same building
REACH = 150           # pixels at 1600x900: how quickly a storage loses weight with distance from an edge
ENOUGH = 2            # fewer recognised storages say too little about a base
# The four edges of the village diamond, as the lines the troops are deployed on
TOP_SIDES = ("tl", "tr")


@dataclass(frozen=True)
class Storage:
    kind: str
    x: float          # relative to the screen, 0..1
    y: float
    score: float


def on_base(x: float, y: float) -> bool:
    """Inside the village diamond and not under one of the game's buttons."""
    if layout.blocked(x, y):
        return False
    margin = 0.03
    for side, (start, end) in layout.SIDES.items():
        line = start[1] + (x - start[0]) * (end[1] - start[1]) / (end[0] - start[0])
        if (side in TOP_SIDES and y < line - margin) or (side not in TOP_SIDES and y > line + margin):
            return False
    return True


class Finder:
    def __init__(self, model: Path = MODEL):
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 2
        options.log_severity_level = 3
        self.session = onnxruntime.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])

    def find(self, image) -> list[Storage]:
        """The storages on a screenshot (BGR, 16:9), the surest first."""
        half = cv2.resize(image, HALF, interpolation=cv2.INTER_AREA)
        hits = []
        for ox, oy in SHIFTS:
            data = (half[oy:, ox:].astype(np.float32) / 255 - 0.5).transpose(2, 0, 1)[None]
            chances = self.session.run(None, {"picture": data})[0][0]
            for kind, name in KINDS.items():
                for row, column in zip(*np.where(chances[kind] > THRESHOLD)):
                    x = (column * STRIDE + WINDOW / 2 + ox) / HALF[0]
                    y = (row * STRIDE + WINDOW / 2 + oy) / HALF[1]
                    if on_base(x, y):
                        hits.append(Storage(name, float(x), float(y), float(chances[kind, row, column])))
        found: list[Storage] = []
        for hit in sorted(hits, key=lambda h: -h.score):
            if all((hit.x - s.x) ** 2 * 1600 ** 2 + (hit.y - s.y) ** 2 * 900 ** 2 > SPACING ** 2 for s in found):
                found.append(hit)
        return found


def side_scores(storages) -> dict[str, float]:
    """How much loot lies near each edge: every storage counts more the closer it is."""
    scores = {}
    for side, (start, end) in layout.SIDES.items():
        ax, ay = start[0] * 1600, start[1] * 900
        dx, dy = end[0] * 1600 - ax, end[1] * 900 - ay
        length = (dx * dx + dy * dy) ** 0.5
        scores[side] = sum(
            s.score * float(np.exp(-abs(dx * (s.y * 900 - ay) - dy * (s.x * 1600 - ax)) / length / REACH))
            for s in storages)
    return scores


def mark(image, found, side) -> np.ndarray:
    """A copy of the picture with the recognised storages and the chosen edge drawn in, to check later."""
    picture = image.copy()
    height, width = picture.shape[:2]
    for storage in found:
        center = (int(storage.x * width), int(storage.y * height))
        colour = (0, 215, 255) if storage.kind == "gold" else (255, 0, 255)
        cv2.circle(picture, center, 40, (0, 0, 0), 6)
        cv2.circle(picture, center, 40, colour, 3)
    if side:
        start, end = (tuple(int(v) for v in (x * width, y * height)) for x, y in layout.SIDES[side])
        cv2.line(picture, start, end, (255, 255, 255), 6)
    return picture


def best_side(storages) -> str | None:
    """The edge with the most loot near it, or None if too few storages were recognised."""
    if len(storages) < ENOUGH:
        return None
    scores = side_scores(storages)
    best = max(scores, key=scores.get)
    # The lower edges are partly hidden behind the troop bar: an almost equal upper edge is better
    if best not in TOP_SIDES:
        top = max(TOP_SIDES, key=scores.get)
        if scores[top] >= 0.85 * scores[best]:
            return top
    return best
