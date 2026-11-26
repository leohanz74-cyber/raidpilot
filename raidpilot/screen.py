"""Reading one screenshot: buttons, numbers and which screen is shown."""
import re
import unicodedata
from difflib import SequenceMatcher

import cv2
import numpy as np

from . import layout
from .ocr import Word

# Typical confusions of the text recognition inside numbers
_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1",
                            "Z": "2", "S": "5", "B": "8"})


# "2x" markers of loot events are not loot
MULTIPLIER = re.compile(r"^[0-9]\s?[xX×]$")


def color_share(patch, low, high) -> float:
    """Part of the picture that lies in the HSV colour range."""
    if patch.size == 0:
        return 0.0
    return float(cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV), low, high).mean()) / 255


def normalize(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def label_matches(text: str, label: str) -> bool:
    a, b = normalize(text), normalize(label)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(b) <= 3:
        return False
    if len(b) >= 6 and b in a and len(a) <= len(b) + 6:
        return True
    return abs(len(a) - len(b)) <= 2 and SequenceMatcher(None, a, b).ratio() >= 0.8


def join_lines(words: list) -> list:
    """Merges words of the same line that stand close together."""
    merged = []
    for word in sorted(words, key=lambda w: (w.y + w.h / 2, w.x)):
        for i, other in enumerate(merged):
            same_row = abs((word.y + word.h / 2) - (other.y + other.h / 2)) < 0.5 * max(word.h, other.h)
            gap = word.x - (other.x + other.w)
            if same_row and -0.5 * word.h <= gap < 1.3 * max(word.h, other.h):
                top = min(other.y, word.y)
                bottom = max(other.y + other.h, word.y + word.h)
                merged[i] = Word(f"{other.text} {word.text}", other.x, top, word.x + word.w - other.x,
                                 bottom - top, min(word.score, other.score))
                break
        else:
            merged.append(word)
    return merged


def parse_number(text: str):
    """'1 234 567' -> 1234567. None if the line is not a number."""
    compact = re.sub(r"[\s.,'’+]", "", text)
    if not compact or "x" in compact.lower() or "×" in compact:  # "2x" markers, "x12" counters
        return None
    digits = sum(c.isdigit() for c in compact)
    if digits == 0 or digits < len(compact) * 0.5:
        return None
    fixed = re.sub(r"\D", "", compact.translate(_DIGIT_FIX))
    if not fixed or len(fixed) > 9:
        return None
    return int(fixed)


def _pick(line_value, box_value):
    """Chooses between two readings of the same number: a lost digit makes one of them shorter."""
    if line_value is None:
        return box_value
    if box_value is not None and box_value != line_value and str(box_value).endswith(str(line_value)):
        return box_value
    return line_value


class Screen:
    def __init__(self, image, ocr):
        self.image = image
        self.ocr = ocr
        self.height, self.width = image.shape[:2]
        self._cache = {}

    def px(self, rel):
        return (int(rel[0] * self.width), int(rel[1] * self.height))

    def crop(self, region):
        x0, y0 = self.px(region[:2])
        x1, y1 = self.px(region[2:])
        return self.image[y0:y1, x0:x1], x0, y0

    def words(self, region=(0, 0, 1, 1)) -> list:
        """Texts inside a region, coordinates relative to the whole picture."""
        if region not in self._cache:
            part, x0, y0 = self.crop(region)
            self._cache[region] = [Word(w.text, w.x + x0, w.y + y0, w.w, w.h, w.score) for w in self.ocr.read(part)]
        return self._cache[region]

    def find_text(self, labels, region=(0, 0, 1, 1), exact_only: bool = False):
        words = self.words(region)
        groups = (words, join_lines(words))
        # Exact hits first, so "Upgrade" does not land on "Upgrade More"
        exact = lambda text, label: normalize(text) == normalize(label)
        for matches in (exact,) if exact_only else (exact, label_matches):
            for candidates in groups:
                for label in labels:
                    for word in candidates:
                        if matches(word.text, label):
                            x, y = word.center
                            return (int(x), int(y))
        return None

    def readable_words(self, region) -> list:
        """Real words of a region. Round shapes read as single letters do not count."""
        return [w for w in self.words(region) if len(normalize(w.text)) >= 3]

    def line(self, region, min_score: float = 0.45) -> str:
        """Text of a region that holds one line, or '' if nothing is readable there."""
        if ("line", region) not in self._cache:
            self._cache["line", region] = self.ocr.line(self.crop(region)[0])
        text, score = self._cache["line", region]
        return text if score >= min_score else ""

    def button(self, name: str, thorough: bool = False):
        """Centre of a button or None. thorough also searches around the usual place."""
        region, labels = layout.BUTTONS[name]
        exact = name in layout.EXACT
        spot = layout.SPOTS.get(name)
        if spot:
            text = self.line(spot)
            same = (lambda a, b: normalize(a) == normalize(b)) if exact else label_matches
            if text and any(same(text, label) for label in labels):
                return self.px(((spot[0] + spot[2]) / 2, (spot[1] + spot[3]) / 2))
            if not thorough:
                return None
        return self.find_text(labels, region, exact)

    def _dimmed(self) -> bool:
        patch = self.crop(layout.BATTLE_PATCH)[0]
        return float(patch.max(axis=2).mean()) < 185

    def home(self, thorough: bool = False):
        """Position of the Battle button if the own village is shown without any window on top."""
        battle = self.button("home_battle", thorough)
        if not battle or not self.button("home_build", thorough):
            return None
        if self._dimmed() and any(self.button(n) for n in ("okay", "cancel", "reload", "claim", "continue")):
            return None
        return battle

    def is_chest(self) -> bool:
        """A reward chest or snack pack: a scene without any text (except "Tap!") and without game buttons."""
        popup = layout.REGIONS["popup"]
        part = self.crop(popup)[0]
        low, high = layout.CHEST_LIGHT
        if not low < float(part.max(axis=2).mean()) < high:
            return False
        if any(not any(known in normalize(w.text) for known in layout.CHEST_WORDS) for w in self.readable_words(popup)):
            return False
        return not any(self.button(name) for name in ("home_battle", "home_build", "end_battle", "return_home"))

    def close_button(self):
        """Position of the red button with the white cross that closes a window, or None."""
        top = self.image[:int(layout.CLOSE_BELOW * self.height)]
        hsv = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 150, 120), (7, 255, 255)) | cv2.inRange(hsv, (170, 150, 120), (180, 255, 255))
        white = cv2.inRange(hsv, (0, 0, 190), (180, 70, 255))
        count, _, boxes, _ = cv2.connectedComponentsWithStats(
            cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)))
        found = []
        for x, y, w, h, _ in boxes[1:count]:
            if not (0.020 * self.width <= w <= 0.055 * self.width and 0.8 <= w / h <= 1.25):
                continue
            cross = cv2.resize(white[y:y + h, x:x + w], (24, 24)) > 127
            # White along both diagonals, but not in the middle of the four edges
            diagonals = np.mean([cross[k - 1:k + 2, c - 1:c + 2].any() for k in range(7, 17) for c in (k, 23 - k)])
            edges = np.mean([cross[3:6, 10:14].mean(), cross[18:21, 10:14].mean(),
                             cross[10:14, 3:6].mean(), cross[10:14, 18:21].mean()])
            if diagonals >= 0.8 and edges <= 0.15:
                found.append((int(w * h), (int(x + w // 2), int(y + h // 2))))
        return max(found)[1] if found else None  # the largest belongs to the window on top

    def contains_word(self, needles, region=(0, 0, 1, 1)) -> bool:
        for word in self.words(region):
            whole = normalize(word.text)
            tokens = {normalize(t) for t in re.split(r"\s+", word.text)}
            for needle in needles:
                # Short words must stand alone, long ones may be part of a word
                if needle in tokens or (len(needle) >= 6 and needle in whole):
                    return True
        # Long phrases can be spread over several words
        joined = "".join(normalize(w.text) for w in join_lines(self.words(region)))
        return any(len(needle) >= 9 and needle in joined for needle in needles)

    def shows_gems(self) -> bool:
        """Safety check: is this about gems or a purchase?"""
        return self.contains_word(layout.PURCHASE_WORDS, layout.REGIONS["popup"])

    def numbers(self, region) -> list:
        """(value, word) of a region from top to bottom."""
        found = []
        words = [w for w in self.words(region) if not MULTIPLIER.match(w.text.strip())]
        for word in sorted(join_lines(words), key=lambda w: (w.y, w.x)):
            value = parse_number(word.text)
            if value is not None:
                found.append((value, word))
        return found

    def _below(self, region, keyword: str, depth: float, max_x: float = 1.0):
        """Numbers listed under the line that contains keyword, or None if there is no such line."""
        anchor = next((w for w in join_lines(self.words(region)) if keyword in normalize(w.text)), None)
        if anchor is None:
            return None
        top = anchor.y + anchor.h * 0.6
        bottom = anchor.y + anchor.h + depth * self.height
        return [value for value, word in self.numbers(region)
                if top < word.center[1] <= bottom and word.x <= max_x * self.width]

    def loot(self):
        """(gold, elixir, dark elixir) of the opponent while scouting or fighting, or None."""
        quick = [parse_number(self.line(row, 0.6)) for row in layout.LOOT_ROWS]
        if quick[0] is not None and quick[1] is not None:
            return (quick[0], quick[1], quick[2] or 0)
        values = self._below(layout.REGIONS["loot"], "loot", 0.20, 0.20)
        if values is None or len(values) < 2:
            return None
        return (values[0], values[1], values[2] if len(values) > 2 else 0)

    def result_loot(self):
        """(gold, elixir, dark elixir) gained according to the result screen, bonus included."""
        found = self._below(layout.REGIONS["result"], "yougot", 0.24, 0.58)
        if found is None:
            return None
        rows = self._result_rows()
        values = [_pick(rows[i], found[i] if i < len(found) else None) for i in range(3)]
        if values[0] is None or values[1] is None:
            return None
        values[2] = values[2] or 0
        bonus = self._below(layout.REGIONS["bonus"], "bonus", 0.20) or []
        return tuple(v + (bonus[i] if i < len(bonus) else 0) for i, v in enumerate(values))

    def _result_rows(self) -> list:
        """Reads the three result lines at their place below "You got". Detecting text boxes
        sometimes cuts off a leading "1", reading the whole line does not."""
        anchor = next(w for w in join_lines(self.words(layout.REGIONS["result"])) if "yougot" in normalize(w.text))
        x, y = anchor.center[0] / self.width, anchor.center[1] / self.height
        values = []
        for index in range(3):
            middle = y + 0.0444 + 0.0667 * index
            region = (x - 0.125, middle - 0.0244, x + 0.0237, middle + 0.0244)
            values.append(parse_number(self.line(region, 0.8)))
        return values

    def storage(self):
        """(gold, elixir) at the top right of the screen, or None."""
        rows = [parse_number(self.line(row, 0.7)) for row in layout.STORAGE_ROWS]
        if None not in rows:
            return (rows[0], rows[1])
        values = [v for v, _ in self.numbers(layout.REGIONS["home_storage"])]
        if len(values) < 2:
            return None
        return (_pick(rows[0], values[0]), _pick(rows[1], values[1]))

    def player_name(self) -> str:
        words = join_lines(self.words(layout.REGIONS["player_name"]))
        words = [w for w in words if len(normalize(w.text)) >= 2]
        return words[0].text.strip()[:30] if words else ""

    def builder_button(self):
        """(idle builders, position) of the '3/6' counter at the bottom right, or None."""
        for word in join_lines(self.words(layout.REGIONS["builders"])):
            match = re.search(r"([0-9Oo])\s*/\s*[0-9]", word.text)
            x, y = word.center
            if match and x < 0.95 * self.width:  # further right is the laboratory counter
                return int(match.group(1).replace("O", "0").replace("o", "0")), (int(x), int(y))
        return None

    # ---------- walls ----------
    def upgrade_panel(self):
        """Position of the open builder list ("Buildings & Heroes"), or None if it is closed."""
        for word in join_lines(self.words(layout.REGIONS["panel_title"])):
            if "buildings" in normalize(word.text):
                return word.center
        for word in join_lines(self.words(layout.REGIONS["builder_list"])):
            if normalize(word.text) in ("suggestedupgrades", "otherupgrades", "upgradesinprogress"):
                return word.center
        return None

    def wall_entries(self) -> list:
        """Wall lines of the builder list from top to bottom: (price or None, position)."""
        region = layout.REGIONS["builder_list"]
        numbers = self.numbers(region)
        entries = []
        for word in sorted(join_lines(self.words(region)), key=lambda w: w.y):
            if not re.fullmatch(r"\d{0,2}wall(x?\d{1,3})?", normalize(word.text)):
                continue
            x, y = word.center
            # The price stands right of the name, a little lower
            price = next((value for value, other in numbers
                          if other.center[0] > x and -0.01 * self.height < other.center[1] - y < 0.05 * self.height
                          and value >= 1000), None)
            entries.append((price, (int(x), int(y))))
        return entries

    def upgrade_buttons(self) -> list:
        """The "Upgrade" buttons of the selected wall from left to right (gold, then elixir).
        "Upgrade More" and the blue wall ring button are left out."""
        found = []
        for word in self.words(layout.REGIONS["wall_buttons"]):
            if not label_matches(word.text, "Upgrade") or "more" in normalize(word.text):
                continue
            above = self.image[max(0, int(word.y - 2.5 * word.h)):int(word.y), int(word.x):int(word.x + word.w)]
            if color_share(above, (90, 130, 110), (118, 255, 255)) > 0.30:
                continue
            x, y = word.center
            found.append((int(x), int(y)))
        return sorted(found)

    def wall_dialog(self):
        """The window "Upgrade Wall to Level N?": (confirm position, price or None, "gold"/"elixir"/None).
        None if this window is not open, so nothing else can ever be confirmed."""
        titles = [normalize(w.text) for w in join_lines(self.words(layout.REGIONS["dialog_title"]))]
        if not any("upgrade" in t and "wall" in t for t in titles):
            return None
        region = layout.REGIONS["confirm"]
        confirm = next((w for w in self.words(region) if label_matches(w.text, "Confirm")), None)
        if confirm is None:
            return None
        x, y = confirm.center
        price = currency = None
        for value, word in self.numbers(region):
            cx, cy = word.center
            if abs(cx - x) < 0.08 * self.width and 0 < cy - y < 0.07 * self.height:
                price = value
                # The coin or the elixir drop follows the price
                icon = self.image[int(cy - 0.045 * self.height):int(cy + 0.045 * self.height),
                                  int(word.x + word.w):int(word.x + word.w + 0.065 * self.width)]
                gold = color_share(icon, (15, 150, 170), (30, 255, 255))
                elixir = color_share(icon, (130, 110, 90), (170, 255, 255))
                if max(gold, elixir) > 0.06:
                    currency = "gold" if gold > elixir else "elixir"
                break
        return (int(x), int(y)), price, currency
