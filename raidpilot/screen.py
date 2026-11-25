"""Ein Bildschirmfoto auswerten: Knoepfe finden, Zahlen lesen."""
import re
import unicodedata
from difflib import SequenceMatcher

import cv2

from . import layout, templates
from .ocr import Word

MATCH_THRESHOLD = 0.86
# Typische Verwechslungen der Texterkennung in Zahlen
_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "Z": "2", "S": "5", "B": "8"})


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.replace("ß", "ss"))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
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
    """Woerter derselben Zeile, die nah beieinander stehen, zusammenfassen."""
    merged = []
    for word in sorted(words, key=lambda w: (w.y + w.h / 2, w.x)):
        for i, other in enumerate(merged):
            same_row = abs((word.y + word.h / 2) - (other.y + other.h / 2)) < 0.5 * max(word.h, other.h)
            gap = word.x - (other.x + other.w)
            if same_row and -0.5 * word.h <= gap < 1.3 * max(word.h, other.h):
                top = min(other.y, word.y)
                bottom = max(other.y + other.h, word.y + word.h)
                merged[i] = Word(f"{other.text} {word.text}", other.x, top, word.x + word.w - other.x, bottom - top, min(word.score, other.score))
                break
        else:
            merged.append(word)
    return merged


def parse_number(text: str):
    """'1 234 567' -> 1234567. None, wenn die Zeile keine Zahl ist."""
    compact = re.sub(r"[\s.,'’+]", "", text)
    if not compact:
        return None
    digits = sum(c.isdigit() for c in compact)
    if digits == 0 or digits < len(compact) * 0.5:
        return None
    fixed = re.sub(r"\D", "", compact.translate(_DIGIT_FIX))
    if not fixed or len(fixed) > 9:
        return None
    return int(fixed)


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
        """Texte in einem Bereich, Koordinaten bezogen auf das ganze Bild."""
        if region not in self._cache:
            part, x0, y0 = self.crop(region)
            self._cache[region] = [Word(w.text, w.x + x0, w.y + y0, w.w, w.h, w.score) for w in self.ocr.read(part)]
        return self._cache[region]

    def match_template(self, image, region=(0, 0, 1, 1), threshold=MATCH_THRESHOLD):
        part, x0, y0 = self.crop(region)
        if image is None or part.shape[0] < image.shape[0] or part.shape[1] < image.shape[1]:
            return None
        scores = cv2.matchTemplate(part, image, cv2.TM_CCOEFF_NORMED)
        _, best, _, where = cv2.minMaxLoc(scores)
        if best < threshold:
            return None
        return (x0 + where[0] + image.shape[1] // 2, y0 + where[1] + image.shape[0] // 2)

    def find_text(self, labels, region=(0, 0, 1, 1)):
        words = self.words(region)
        groups = (words, join_lines(words))
        # Erst genaue Treffer, damit "Upgrade" nicht auf "Upgrade More" landet
        exact = lambda text, label: normalize(text) == normalize(label)
        for matches in (exact, label_matches):
            for candidates in groups:
                for label in labels:
                    for word in candidates:
                        if matches(word.text, label):
                            x, y = word.center
                            return (int(x), int(y))
        return None

    def button(self, name: str):
        """Mittelpunkt eines Knopfs oder None. Eigene Vorlagen haben Vorrang."""
        region, labels = layout.BUTTONS[name]
        for entry in templates.index():
            if entry["kind"] == "button" and entry["name"] == name:
                hit = self.match_template(templates.load_image(entry, self.width))
                if hit:
                    return hit
        return self.find_text(labels, region)

    def contains_word(self, needles, region=(0, 0, 1, 1)) -> bool:
        for word in self.words(region):
            whole = normalize(word.text)
            tokens = {normalize(t) for t in re.split(r"\s+", word.text)}
            for needle in needles:
                # Kurze Woerter muessen allein stehen, lange duerfen Teil sein
                if needle in tokens or (len(needle) >= 6 and needle in whole):
                    return True
        return False

    def shows_gems(self) -> bool:
        """Sicherheitsabfrage: geht es um Juwelen oder einen Kauf?"""
        return self.contains_word(layout.PURCHASE_WORDS, layout.REGIONS["popup"])

    def numbers(self, region) -> list:
        """Zahlen eines Bereichs von oben nach unten."""
        found = []
        for word in sorted(join_lines(self.words(region)), key=lambda w: (w.y, w.x)):
            value = parse_number(word.text)
            if value is not None:
                found.append((value, word))
        return found

    def loot(self):
        """(Gold, Elixier, Dunkles Elixier) im Spaehbildschirm oder None."""
        values = [v for v, _ in self.numbers(layout.REGIONS["loot"])]
        if len(values) < 2:
            return None
        return (values[0], values[1], values[2] if len(values) > 2 else 0)

    def storage(self):
        """(Gold, Elixier) oben rechts im eigenen Dorf oder None."""
        values = [v for v, _ in self.numbers(layout.REGIONS["home_storage"])]
        if len(values) < 2:
            return None
        return (values[0], values[1])
