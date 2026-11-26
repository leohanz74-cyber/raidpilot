"""Reading one screenshot: buttons, numbers and which screen is shown."""
import re
import unicodedata
from difflib import SequenceMatcher

from . import layout
from .ocr import Word

# Typical confusions of the text recognition inside numbers
_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1",
                            "Z": "2", "S": "5", "B": "8"})


# "2x" markers of loot events are not loot
MULTIPLIER = re.compile(r"^[0-9]\s?[xX×]$")


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
        if self._dimmed() and (self.button("okay") or self.button("cancel") or self.button("reload")):
            return None
        return battle

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

    def free_builders(self):
        """Number of idle builders ('0/6' at the bottom right) or None."""
        for word in join_lines(self.words(layout.REGIONS["builders"])):
            match = re.search(r"([0-9Oo])\s*/\s*[0-9]", word.text)
            if match:
                return int(match.group(1).replace("O", "0").replace("o", "0"))
        return None
