"""A simulated game with the interface of Adb. It draws the screens in the layout of the real game
(1600x900) and reacts to taps."""
import cv2
import numpy as np

W, H = 1600, 900
CARD = 108
HEROES = ("king", "queen", "warden")
# The builder list: headers and other buildings first, the walls far down
OTHER_ROWS = ("Suggested upgrades", "Laboratory", "Elixir Collector", "Other upgrades", "Dragon Duke",
              "Spiky Tower", "Monolith", "Clan Castle", "Spell Factory", "Gold Mine x 5", "Gold Storage x 4",
              "Smasher", "Crafting Station")
ROW = 72


class FakeGame:
    def __init__(self, loots=((900_000, 120_000, 800), (650_000, 680_000, 3_200)),
                 storage=(5_000_000, 4_000_000), welcome=False, serial="emulator-5554"):
        # walls: [price, how many]; the list scrolls; refuse = currencies the game says are not enough
        self.walls = [[4_800_000, 2], [4_000_000, 3]]
        self.scroll = 0
        self.wall = None
        self.currency = None
        self.refuse = set()
        self.builders = 1
        self.bar_delay = 0
        self.scout_frames = 0
        self.chest_taps = 0
        self.serial = ""
        self.configured = ""
        self.path = "fake-adb"
        self.online = serial
        self.loots = list(loots)
        self.storage = list(storage)
        self.state = "welcome" if welcome else "home"
        self.base = 0
        self.ticks = 0
        self.now = 0.0
        self.taps = []
        self.deployed = {}
        self.events = []
        self.selected = None
        self.after_attack = None
        self.endless = False
        self.raid_started = self.raid_ended = None
        self._reset_army()

    def _reset_army(self):
        # name, count (None = hero), colour, left edge
        self.army = [["dragon", 14, (60, 190, 90), 118], ["event", 30, (60, 180, 90), 253],
                     ["siege", 1, (200, 150, 70), 387], ["king", None, (40, 90, 220), 508],
                     ["queen", None, (60, 200, 190), 629], ["warden", None, (200, 40, 180), 750],
                     ["rage", 5, (210, 90, 210), 885]]

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    # ---------- Adb interface ----------
    def devices(self, connect=True):
        return [{"serial": self.online, "state": "device"}] if self.online else []

    def connect(self, serial):
        self.events.append("connect:" + serial)

    def restart_server(self):
        pass

    def launch_game(self):
        self.events.append("launch")

    def stop_game(self):
        self.events.append("stop")
        self.state = "home"

    def zoom_out(self, size):
        self.events.append("zoom:" + self.state)
        return True

    def back(self):
        self.events.append("back")
        if self.state in ("menu", "army"):
            self.state = "home"
        elif self.state == "popup":
            self.state = "dialog"
        elif self.state == "dialog":
            self.state = "panel"
        elif self.state == "panel":
            self.state = "home"
            self.wall = None

    def swipe(self, x1, y1, x2, y2, duration=0):
        self.events.append("swipe")
        if self.state == "panel" and x1 > 1170:
            rows = len(self.rows())
            self.scroll = max(0, min(max(0, rows - 10), self.scroll + (4 if y2 < y1 else -4)))

    def rows(self):
        """(name, price or None, wall index or None) of the builder list."""
        rows = [(name, None if name.endswith("upgrades") else 90_000_000, None) for name in OTHER_ROWS]
        for index, (price, amount) in enumerate(self.walls):
            if amount:
                rows.append((f"Wall x {amount}" if amount > 1 else "Wall", price, index))
        return rows

    def visible_rows(self):
        return [(90 + (i - self.scroll) * ROW, row) for i, row in enumerate(self.rows())
                if 0 <= i - self.scroll < 10]

    def screenshot(self):
        self.now += 0.3
        if self.state == "clouds":
            self.ticks += 1
            if self.ticks >= 2:
                self.state = "scout"
        elif self.state == "scout":
            self.scout_frames += 1
        elif self.state == "battle":
            self.ticks += 1
            if self.ticks >= 14 and not self.endless:
                self.state = "result"
        return self.render()

    def tap_many(self, points):
        for point in points:
            self.tap(*point)

    def tap(self, x, y):
        self.now += 0.05
        self.taps.append((self.state, x, y))
        near = lambda px, py, w=100, h=40: abs(x - px) <= w and abs(y - py) <= h
        if self.state == "welcome" and near(820, 749):
            self.state = "home"
        elif self.state == "home" and near(107, 858):
            self.state = "menu"
        elif self.state == "home" and near(1455, 696, 60):
            self.state = "panel"
            self.scroll = 0
            self.wall = None
        elif self.state == "panel":
            if x >= 1170:
                for row_y, (_, _, wall) in self.visible_rows():
                    if wall is not None and abs(y - row_y - 8) <= 30:
                        self.wall = wall
                        self.events.append(f"select:{wall}")
            elif self.wall is not None and 780 <= y <= 890:
                for name, cx in (("gold", 399), ("elixir", 572), ("ring", 750)):
                    if abs(x - cx) <= 65:
                        if name == "ring":
                            self.events.append("ring")
                        else:
                            self.currency = name
                            self.state = "dialog"
        elif self.state == "dialog" and near(1115, 770, 125, 55):
            price = self.walls[self.wall][0]
            mine = 0 if self.currency == "gold" else 1
            if self.currency in self.refuse or self.storage[mine] < price:
                self.state = "popup"
            else:
                self.storage[mine] -= price
                self.walls[self.wall][1] -= 1
                self.events.append("wall:" + self.currency)
                self.state = "panel"
                if not self.walls[self.wall][1]:
                    self.wall = None
        elif self.state == "popup" and near(746, 569, 120, 50):
            self.events.append("gems")
        elif self.state == "chest" and near(752, 504, 160, 120):
            self.chest_taps += 1
            if self.chest_taps >= 3:
                self.state = "reward"
        elif self.state == "reward" and near(772, 792, 140, 45):
            self.events.append("reward")
            self.state = "home"
        elif self.state == "menu" and near(246, 643, 150):
            self.state = "army"
        elif self.state == "army" and near(1439, 799):
            self._search()
        elif self.state in ("scout", "battle"):
            if self.state == "scout" and near(1491, 617, 70):
                self.base += 1
                self._search()
            elif near(116, 669, 90, 30):
                self.events.append("end")
                self.raid_ended = self.now
                self.state = "home" if self.state == "scout" else "confirm"
            elif y >= 740:
                for index, (name, _, _, left) in enumerate(self.army):
                    if left <= x <= left + CARD:
                        self.events.append("card:" + name)
                        if name in HEROES and self.deployed.get(name):
                            self.events.append("ability:" + name)
                        self.selected = index
            elif self.selected is not None:
                self._deploy(x, y)
        elif self.state == "confirm" and near(960, 560):
            self.state = "result"
        elif self.state == "result" and near(770, 755, 150, 50):
            self.state = "home"
            self.ticks = 0
            got = self.total()
            self.storage[0] += got[0]
            self.storage[1] += got[1]
            if self.after_attack:
                self.after_attack()

    # ---------- game logic ----------
    def _search(self):
        self.scout_frames = 0
        self.state = "clouds"
        self.ticks = 0
        self.selected = None
        self._reset_army()

    def _deploy(self, x, y):
        name, count = self.army[self.selected][:2]
        inside_base = abs(x / W - 0.505) / 0.37 + abs(y / H - 0.455) / 0.40 < 1
        if inside_base and name != "rage":
            self.events.append("redzone")
            return
        if count == 0 or (count is None and self.deployed.get(name)):
            return
        self.deployed[name] = self.deployed.get(name, 0) + 1
        if count is not None:
            self.army[self.selected][1] -= 1
        if name != "rage" and self.state == "scout":
            self.state = "battle"
            self.ticks = 0
            self.raid_started = self.now

    def loot_full(self):
        return self.loots[min(self.base, len(self.loots) - 1)]

    def got(self):
        return tuple(int(v * 0.7) for v in self.loot_full())

    bonus = (50_000, 60_000, 500)

    def total(self):
        return tuple(a + b for a, b in zip(self.got(), self.bonus))

    # ---------- drawing ----------
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

        def button(value, x, y, w=220, color=(40, 150, 235), h=68, scale=1.0):
            cv2.rectangle(image, (x - w // 2, y - h // 2), (x + w // 2, y + h // 2), color, -1)
            text(value, x, y, scale, center=True)

        spaced = lambda n: f"{n:,}".replace(",", " ")
        if self.state in ("home", "welcome", "menu", "army"):
            text(spaced(self.storage[0]), 1365, 55, 0.9)
            text(spaced(self.storage[1]), 1365, 118, 0.9)
            text("TestChief", 135, 75, 0.9)
            button("Build", 1495, 855, 120)
            text(f"{self.builders}/6", 1430, 705, 0.9)
        if self.state in ("panel", "dialog", "popup"):
            text(spaced(self.storage[0]), 930, 55, 0.9)
            text(spaced(self.storage[1]), 930, 118, 0.9)
            cv2.rectangle(image, (1172, 0), (1600, 900), (80, 95, 120), -1)
            text("Buildings & Heroes", 1379, 26, 0.8, center=True)
            for y, (name, price, wall) in self.visible_rows():
                cv2.rectangle(image, (1180, y - 28), (1590, y + 38), (110, 140, 180), -1)
                text(name, 1230, y + 8, 0.7)
                if price:
                    text(spaced(price), 1440, y + 30, 0.65)
                    cv2.circle(image, (1575, y + 22), 9, (220, 60, 200), -1)
            if self.wall is not None:
                for label, cx, color in (("gold", 399, (150, 185, 205)), ("elixir", 572, (150, 185, 205)),
                                         ("ring", 750, (235, 150, 40))):
                    cv2.rectangle(image, (cx - 65, 760), (cx + 65, 890), color, -1)
                    text("Upgrade", cx, 862, 0.75, center=True)
                button("Upgrade", 748, 664, 130, (150, 185, 205), 36, 0.7)
                button("More", 748, 700, 130, (150, 185, 205), 36, 0.7)
        if self.state in ("dialog", "popup"):
            price = self.walls[self.wall][0] if self.wall is not None else 0
            cv2.rectangle(image, (130, 10), (1450, 885), (90, 100, 110), -1)
            level = "19" if self.wall == 0 else "18"
            text(f"Upgrade Wall to Level {level}?", 791, 57, 1.3, center=True)
            cv2.rectangle(image, (750, 150), (1420, 700), (245, 245, 245), -1)
            cv2.rectangle(image, (985, 725), (1245, 835), (60, 200, 130), -1)
            text("Confirm", 1115, 755, 0.9, center=True)
            text(spaced(price), 1090, 790, 0.9, center=True)
            cv2.circle(image, (1195, 790), 22, (40, 190, 250) if self.currency == "gold" else (220, 60, 200), -1)
        if self.state == "popup":
            cv2.rectangle(image, (500, 230), (1160, 640), (225, 235, 240), -1)
            text(f"Need more {self.currency.title()}", 830, 285, 1.1, center=True)
            text("Buy the missing amount?", 830, 420, 0.9, center=True)
            button("882", 746, 569, 240, (70, 190, 90), 90)
        if self.state == "chest":
            image[:] = (40, 55, 90)
            cv2.circle(image, (752, 450), 150, (30, 40, 190), -1)
        elif self.state == "reward":
            image[:] = (40, 55, 90)
            text("2x Battle Bake", 770, 90, 1.2, center=True)
            text("Item delivered to the Temporary Storage.", 770, 720, 0.8, center=True)
            button("Continue", 772, 792, 260, (60, 200, 130), 80)
        if self.state in ("home", "welcome"):
            button("Battle", 107, 858, 190)
            if self.state == "welcome":
                image[:] = (image * 0.5).astype(np.uint8)
                cv2.rectangle(image, (350, 120), (1250, 820), (225, 235, 240), -1)
                text("Welcome Back Chief!", 800, 190, 1.4, center=True)
                button("Okay", 820, 749, 220, (70, 170, 70))
        elif self.state == "menu":
            button("Find a Match", 246, 643, 320)
        elif self.state == "army":
            button("Attack!", 1439, 799)
        elif self.state == "clouds":
            image[:] = (200, 200, 200)
        elif self.state in ("scout", "battle", "confirm"):
            part = 1.0 if self.state == "scout" else max(0.5 if self.endless else 0.0, 1 - self.ticks / 20)
            text("Available Loot:", 78, 82, 0.75)
            for value, y in zip(self.loot_full(), (138, 188, 240)):
                text(spaced(int(value * part)), 82, y, 0.9)
            text("Battle starts in:" if self.state == "scout" else "Battle ends in:", 800, 40, 0.8, center=True)
            button("End Battle", 116, 669, 180, (50, 60, 210), 56, 0.9)
            if self.state == "scout":
                button("Next", 1491, 617, 120, h=90)
            cv2.rectangle(image, (0, 735), (W, H), (32, 32, 32), -1)
            late = self.state == "scout" and 0 < self.bar_delay and self.scout_frames <= self.bar_delay
            for index, (name, count, color, left) in enumerate([] if late else self.army):
                used = count == 0
                placed = name in HEROES and self.deployed.get(name)
                if placed:
                    color = (125, 125, 125)
                cv2.rectangle(image, (left, 746), (left + CARD, 884), (70, 70, 70) if used else color, -1)
                cv2.circle(image, (left + 54, 835), 24, (60, 60, 60) if used else color if placed else (30, 220, 240), -1)
                if name == "rage" and not used:
                    cv2.rectangle(image, (left + 8, 786), (left + CARD - 8, 876), color, -1)
                if name == "event" and not used:
                    cv2.rectangle(image, (left + 6, 749), (left + 37, 779), (170, 215, 250), -1)
                if count is not None:
                    text(f"x{count}", left + 44, 776, 0.8)
                elif placed:
                    raised = 3 if index == self.selected else 0
                    cv2.rectangle(image, (left + 4, 710 - raised), (left + CARD - 4, 733 - raised), (25, 25, 25), -1)
                    cv2.rectangle(image, (left + 8, 721 - raised), (left + CARD - 8, 729 - raised), (30, 235, 100), -1)
            if self.state == "confirm":
                cv2.rectangle(image, (450, 250), (1150, 620), (225, 225, 225), -1)
                text("Surrender battle?", 800, 320, 1.1, center=True)
                button("Cancel", 640, 560, color=(60, 60, 200))
                button("Okay", 960, 560, color=(70, 170, 70))
        elif self.state == "result":
            text("Victory", 800, 130, 2.0, center=True)
            text("You got:", 802, 373, 0.9, center=True)
            for value, y in zip(self.got(), (414, 474, 534)):
                text(spaced(value), 765, y, 1.0, center=True)
            text("2x", 960, 424, 0.9)
            text("100% Bonus:", 1200, 380, 0.8, center=True)
            for value, y in zip(self.bonus, (425, 480, 535)):
                text("+" + str(value), 1150, y, 0.9)
            cv2.rectangle(image, (680, 715), (860, 800), (70, 170, 70), -1)
            text("Return", 770, 742, 0.8, center=True)
            text("Home", 770, 778, 0.8, center=True)
        return image


class FakeMumu:
    """MuMu Player instance that needs a moment to boot."""
    available = True
    index = 0

    def __init__(self, game):
        self.game = game
        self.launched = False
        self.polls = 0
        game.online = ""

    def info(self):
        if self.launched:
            self.polls += 1
        if self.launched and self.polls >= 3:
            self.game.online = "127.0.0.1:16384"
            return {"is_android_started": True, "adb_port": 16384, "adb_host_ip": "127.0.0.1"}
        return {"is_android_started": False}

    def launch(self):
        self.launched = True

    @staticmethod
    def serial_of(info):
        from raidpilot.mumu import Mumu

        return Mumu.serial_of(info)
