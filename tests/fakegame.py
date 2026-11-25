"""Nachgestelltes Spiel mit derselben Schnittstelle wie Adb. Zeichnet Bildschirme und reagiert auf Tippen."""
import cv2
import numpy as np

W, H = 1280, 720
STEP = 92
BAR_START = 200
COUNT_Y = 606


class FakeGame:
    def __init__(self, loots=((100_000, 120_000, 800), (450_000, 480_000, 3_200)), storage=(5_000_000, 4_000_000)):
        self.serial = ""
        self.configured = ""
        self.loots = list(loots)
        self.storage = list(storage)
        self.state = "home"
        self.base = 0
        self.ticks = 0
        self.now = 0.0
        self.taps = []
        self.deployed = {}
        self.events = []
        self.selected = None
        self._reset_army()
        self.path = "fake-adb"

    def _reset_army(self):
        # (Name, Anzahl oder None, Farbe)
        self.army = [["dragon", 10, (60, 180, 90)], ["siege", 1, (90, 140, 200)], ["king", None, (40, 90, 220)],
                     ["queen", None, (200, 80, 160)], ["rage", 3, (210, 90, 210)]]

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    # ---------- Adb-Schnittstelle ----------
    def devices(self, connect=True):
        return [{"serial": "emulator-5554", "state": "device"}]

    def restart_server(self):
        pass

    def launch_game(self):
        self.events.append("launch")

    def stop_game(self):
        self.events.append("stop")
        self.state = "home"

    def back(self):
        self.events.append("back")

    def swipe(self, *args):
        self.events.append("swipe")

    def screenshot(self):
        self.now += 0.3
        if self.state == "clouds":
            self.ticks += 1
            if self.ticks >= 2:
                self.state = "scout"
        elif self.state == "battle":
            self.ticks += 1
            if self.ticks >= 14:
                self.state = "result"
        return self.render()

    def tap(self, x, y):
        self.now += 0.05
        self.taps.append((self.state, x, y))
        near = lambda px, py, w=110, h=40: abs(x - px) <= w and abs(y - py) <= h
        if self.state == "home" and near(110, 650):
            self.state = "menu"
        elif self.state == "menu" and near(300, 450, 160):
            self.state = "army"
        elif self.state == "army" and near(1130, 650):
            self._search()
        elif self.state in ("scout", "battle"):
            if self.state == "scout" and near(1180, 540, 80):
                self.base += 1
                self._search()
            elif near(110, 540, 120):
                self.events.append("end")
                self.state = "home" if self.state == "scout" else "confirm"
            elif y > 0.82 * H:
                index = round((x - BAR_START) / STEP)
                if 0 <= index < len(self.army):
                    name = self.army[index][0]
                    if name in ("king", "queen") and self.deployed.get(name):
                        self.events.append("ability:" + name)
                    self.selected = index
            elif self.selected is not None:
                self._deploy(x, y)
        elif self.state == "confirm" and near(780, 480):
            self.state = "result"
        elif self.state == "result" and near(640, 620, 140):
            self.state = "home"
            self.storage[0] += self.loot_now()[0]
            self.storage[1] += self.loot_now()[1]

    # ---------- Spiellogik ----------
    def _search(self):
        self.state = "clouds"
        self.ticks = 0
        self.selected = None
        self._reset_army()

    def _deploy(self, x, y):
        name, count, _ = self.army[self.selected]
        inside_base = abs(x / W - 0.5) / 0.33 + abs(y / H - 0.43) / 0.33 < 1
        if inside_base and name != "rage":
            self.events.append("redzone")
            return
        if count == 0:
            return
        self.deployed[name] = self.deployed.get(name, 0) + 1
        if count is not None:
            self.army[self.selected][1] -= 1
        if name != "rage" and self.state == "scout":
            self.state = "battle"
            self.ticks = 0

    def loot_full(self):
        return self.loots[min(self.base, len(self.loots) - 1)]

    def loot_now(self):
        part = max(0.0, 1 - self.ticks / 20) if self.state == "battle" else 1.0
        if self.state in ("result", "home", "confirm"):
            part = 0.3
        full = self.loot_full()
        return tuple(int(v * (part if self.state == "battle" else 1 - part if self.state in ("result", "home") else part)) for v in full)

    # ---------- Zeichnen ----------
    def render(self):
        rng = np.random.default_rng(3)
        image = np.full((H, W, 3), (62, 104, 74), np.uint8)
        image = np.clip(image.astype(int) + rng.integers(-5, 6, (H, W, 1)), 0, 255).astype(np.uint8)

        def text(value, x, y, scale=1.0, color=(255, 255, 255), center=False):
            if center:
                (tw, th), _ = cv2.getTextSize(value, cv2.FONT_HERSHEY_DUPLEX, scale, 2)
                x, y = x - tw // 2, y + th // 2
            cv2.putText(image, value, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, (0, 0, 0), 7, cv2.LINE_AA)
            cv2.putText(image, value, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, color, 2, cv2.LINE_AA)

        def button(value, x, y, w=220, color=(40, 150, 235)):
            cv2.rectangle(image, (x - w // 2, y - 36), (x + w // 2, y + 36), color, -1)
            text(value, x, y, 0.95, center=True)

        spaced = lambda n: f"{n:,}".replace(",", " ")
        if self.state in ("home", "menu", "army"):
            text(spaced(self.storage[0]), 1070, 55, 0.9)
            text(spaced(self.storage[1]), 1070, 110, 0.9)
            text("2/5", 600, 45, 0.8)
        if self.state == "home":
            button("Attack!", 110, 650, 190)
        elif self.state == "menu":
            button("Find a Match", 300, 450, 320)
        elif self.state == "army":
            button("Attack!", 1130, 650)
        elif self.state == "clouds":
            image[:] = (200, 200, 200)
        elif self.state in ("scout", "battle", "confirm"):
            loot = self.loot_now()
            text("Available Loot:", 25, 90, 0.65)
            for i, value in enumerate(loot):
                text(spaced(value), 60, 130 + i * 40, 0.85)
            button("End Battle", 110, 540, 190, (50, 60, 210))
            if self.state == "scout":
                button("Next", 1180, 540, 150)
            cv2.rectangle(image, (0, 590), (W, H), (35, 35, 35), -1)
            for i, (name, count, color) in enumerate(self.army):
                x = BAR_START + i * STEP
                cv2.rectangle(image, (x - 40, 590), (x + 40, 710), color, -1)
                cv2.circle(image, (x, 670), 22, (30, 220, 240), -1)
                cv2.rectangle(image, (x - 30, 690), (x + 10, 705), (250, 250, 250), -1)
                if count is not None:
                    text(f"x{count}", x - 28, COUNT_Y + 14, 0.8)
            if self.state == "confirm":
                cv2.rectangle(image, (300, 220), (980, 530), (225, 225, 225), -1)
                text("Surrender battle?", 640, 280, 1.0, center=True)
                button("Cancel", 500, 480, 200, (60, 60, 200))
                button("Okay", 780, 480, 200, (70, 170, 70))
        elif self.state == "result":
            text("You got:", 640, 240, 1.0, center=True)
            got = [int(v * 0.7) for v in self.loot_full()]
            for i, value in enumerate(got):
                text(spaced(value), 640, 320 + i * 55, 1.0, center=True)
            button("Return Home", 640, 620, 290, (70, 170, 70))
        return image
