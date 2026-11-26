"""The automation: emulator -> game -> own village -> search -> attack -> back home.
Everything happens through screenshots and touch input."""
import random
import re
import threading
import time
import traceback

import numpy as np

from . import army, layout, notify, power, screen as screen_mod, storages
from .adb import AdbError
from .mumu import MumuError

MAX_BATTLE = 90           # seconds after the first troop until a battle is ended at the latest
MIN_BATTLE = 50           # never end for lack of loot before this
STALE_AFTER = 22          # seconds without new loot
LOOT_DONE = 0.05          # end once only this share of the loot is left ...
LOOT_DONE_AFTER = 20      # ... and at least this many seconds have passed
SPELL_DELAY = 7           # seconds after the first troop until the first half of the spells
SPELL_WAVE_GAP = 8        # seconds between the two halves
# A calm, fixed pace: fewer pictures to analyse, and a lagging emulator can keep up
BATTLE_LOOK = 1.5         # seconds between two looks at a running battle
BUTTON_LOOK = 0.5         # seconds between two looks while waiting for a button
TAP_PAUSE = 0.25          # after choosing a card or casting a spell
BATCH_PAUSE = 0.2         # between two groups of troop taps
COUNT_PAUSE = 0.7         # until the counter of a card shows what has landed
TROOP_LOOKS = 5           # attempts to read the troop bar before a battle is given up
ABILITY_DELAY = 12        # seconds after the heroes are placed
WARDEN_GAP = 5            # the Grand Warden's ability comes this much after all others
LINE_STEPS = (0.0, 0.012, -0.025, -0.045, -0.065)   # tried in turn when nothing lands on the line
HERO_STEPS = (0.0, -0.03, 0.025)
MAX_SEARCHES = 60
UNKNOWN_RELAUNCH = 16     # unknown pictures in a row until the game is restarted
BOOT_TIMEOUT = 240
WALLS_PER_VISIT = 15
WALL_SCROLLS = 22         # swipes through the builder list while looking for walls
WALL_TRIGGER = 0.5        # walls are upgraded once a storage is this full
WALL_FLOOR = 1_000_000    # after buying, stop when gold and elixir are both below this
WALL_PAUSE = 5            # village visits without a new try after walls did not work
REWARD_TAPS = 30          # taps through reward screens before giving up


NOT_ENOUGH = "Not enough gold or elixir for the next wall."
SIDE_NAMES = {"tl": "Top Left", "tr": "Top Right", "bl": "Bottom Left", "br": "Bottom Right"}


class Stop(Exception):
    """The user pressed Stop."""


class Done(Exception):
    """Goal reached, finish cleanly."""


class BotError(Exception):
    """Going on would be pointless or risky."""


class Bot:
    def __init__(self, adb, ocr, get_settings, stats, log, emulator=None, clock=time.monotonic, sleep=None,
                 rng=None, on_player=None, on_capture=None):
        self.adb = adb
        self.ocr = ocr
        self.get_settings = get_settings
        self.stats = stats
        self.log = log
        self.emulator = emulator
        self.clock = clock
        self._sleep = sleep
        self.rng = rng or random.Random()
        self.on_player = on_player
        self.on_capture = on_capture
        self._zoomed = False
        self._counted = False
        self._wall_pause = 0
        self._finder = None
        self._reward_stuck = False
        self._stop = threading.Event()
        self._thread = None
        self.status = "Ready"
        self.last_error = ""
        self.size = (1600, 900)
        self.failures = 0
        self._warned = set()

    # ---------- control ----------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.last_error = ""
        self._thread = threading.Thread(target=self.run, name="raidpilot-bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.running:
            self.status = "Stopping…"
        self._stop.set()

    def join(self, timeout=None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def run(self) -> None:
        """Blocking main loop (the tests call it directly)."""
        self.stats.start()
        self.failures = 0
        self._warned = set()
        self._zoomed = False
        self._wall_pause = 0
        adb_errors = 0
        reason = "Stopped"
        if power.keep_awake(True):
            self.log("The PC stays awake while the bot runs. The screen may turn off.")
        try:
            self._connect(self.get_settings())
            self._start_game()
            while True:
                self._check_stop()
                try:
                    self._cycle(self.get_settings())
                    adb_errors = 0
                except AdbError as exc:
                    adb_errors += 1
                    self.log(f"Connection: {exc}", "warn")
                    if adb_errors >= 5:
                        raise BotError("The connection to the emulator is lost.") from exc
                    self._wait(5)
                    if adb_errors >= 2:
                        self._connect(self.get_settings())
                if self.failures >= 5:
                    raise BotError("No attack was possible five times in a row.")
        except Stop:
            pass
        except Done as exc:
            reason = str(exc)
            self.log(reason, "good")
        except (BotError, AdbError, MumuError) as exc:
            reason = self.last_error = str(exc)
            self.log(reason, "error")
        except Exception as exc:  # unexpected: report it instead of dying silently
            reason = self.last_error = f"Unexpected error: {exc}"
            self.log(reason, "error")
            self.log(traceback.format_exc(), "error")
        finally:
            power.keep_awake(False)
            self.stats.stop()
            self.status = "Error" if self.last_error else "Ready"
            self.log("Bot stopped.")
            self._report(f"RaidPilot stopped: {reason}")

    # ---------- helpers ----------
    def _dismiss(self, shot) -> None:
        """Closes the window on top: its red X, or the back key if it has none.
        (The builder list ignores the back key.)"""
        close = shot.close_button()
        if close:
            self._tap(close, 0.8)
        else:
            self.adb.back()
            self._wait(0.8)

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise Stop()

    def _wait(self, seconds: float) -> None:
        self._check_stop()
        if self._sleep:
            self._sleep(seconds)
        else:
            self._stop.wait(seconds)
        self._check_stop()

    def _shot(self):
        self._check_stop()
        shot = screen_mod.Screen(self.adb.screenshot(), self.ocr)
        self.size = (shot.width, shot.height)
        return shot

    def _tap(self, point, pause: float = 0.0) -> None:
        self._check_stop()
        self.adb.tap(*point)
        if pause:
            self._wait(pause)

    def _capture(self, name: str, shot) -> None:
        if self.on_capture:
            try:
                self.on_capture(name, shot.image)
            except OSError:
                pass

    def _find_any(self, shot, names, thorough: bool = False):
        for name in names:
            point = shot.button(name, thorough)
            if point:
                return name, point
        return None, None

    def _reward_target(self, shot):
        """What to tap next on a reward screen, or None. Nothing is touched where money is mentioned."""
        popup = layout.REGIONS["popup"]
        if shot.contains_word(layout.BUY_WORDS, popup):
            return None
        point = shot.button("claim") or shot.find_text(layout.BUTTONS["continue"][1], popup)
        if point:
            return point
        return shot.px(layout.POINTS["chest"]) if shot.is_chest() else None

    def _collect_rewards(self, shot) -> bool:
        """Taps through chests, snack packs and star bonus screens until they are gone.
        True if a reward screen was there and is gone now."""
        if self._reward_stuck or not self._reward_target(shot):
            return False
        self._wait(0.6)  # a fading screen can look like a chest for a moment
        shot = self._shot()
        point = self._reward_target(shot)
        if not point:
            return False
        before = self.status
        self.status = "Collecting rewards…"
        self.log("Collecting a reward…")
        self._capture("last_reward", shot)
        for _ in range(REWARD_TAPS):
            self._tap(point, 1.0)
            point = self._reward_target(self._shot())
            if not point:
                self._wait(1.2)  # the screen flashes white between two steps
                point = self._reward_target(self._shot())
                if not point:
                    self.log("Reward collected.", "good")
                    break
        else:
            # Probably something else: leave it to the usual ways back, which can restart the game
            self._reward_stuck = True
            self._capture("reward_stuck", self._shot())
            self.log("The reward screen does not close.", "warn")
        self.status = before
        return not self._reward_stuck

    def _wait_for(self, names, timeout: float, interval: float = BUTTON_LOOK, rewards: bool = False):
        """Waits for one of the buttons. Handles dialogs that can appear while an attack starts.
        With rewards=True a reward screen is collected too and reported as "reward"."""
        began = self.clock()
        while True:
            shot = self._shot()
            waited = self.clock() - began
            # Reading the whole screen is slow: only do it when the button takes unusually long
            name, point = self._find_any(shot, names, waited >= 4)
            if name:
                return shot, name, point
            if waited >= 2.5:
                if rewards and self._collect_rewards(shot):
                    return shot, "reward", None
                if shot.shows_gems():
                    self.adb.back()
                    raise BotError("The game asks for gems (not enough gold to search?). Nothing was bought.")
                if shot.contains_word(("shield",), layout.REGIONS["popup"]) and shot.button("okay"):
                    self._tap(shot.button("okay"))
            if waited >= timeout:
                return shot, None, None
            self._wait(interval)

    def _wait_gone(self, name: str, timeout: float) -> bool:
        end = self.clock() + timeout
        while self.clock() < end:
            self._wait(BUTTON_LOOK)
            if not self._shot().button(name):
                return True
        return False

    def _warn_once(self, key: str, text: str, level: str = "warn") -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.log(text, level)

    def _report(self, headline: str) -> None:
        url = self.get_settings().get("webhook")
        if not url:
            return
        s = self.stats.snapshot()
        notify.send(url, f"{headline}\nAttacks: {s['attacks']} · Gold: {notify.short(s['gold'])} · "
                         f"Elixir: {notify.short(s['elixir'])} · Walls: {s['walls']}", self.log)

    # ---------- emulator and game ----------
    def _online(self, search: bool = True) -> list:
        return [d["serial"] for d in self.adb.devices(connect=search) if d["state"] == "device"]

    def _boot_emulator(self) -> str:
        """Starts MuMu Player instance #0 if needed and returns its ADB address."""
        mumu = self.emulator
        info = mumu.info()
        serial = mumu.serial_of(info)
        if not serial:
            self.status = "Starting emulator…"
            self.log(f"Starting MuMu Player instance #{mumu.index}…")
            mumu.launch()
            end = self.clock() + BOOT_TIMEOUT
            while not serial:
                if self.clock() >= end:
                    raise BotError("MuMu Player did not finish starting in time.")
                self._wait(4)
                serial = mumu.serial_of(mumu.info())
            self.log("Emulator is running.", "good")
            self._wait(3)
        return serial

    def _connect(self, settings) -> None:
        self.status = "Connecting…"
        wanted = settings["device"]
        has_mumu = self.emulator is not None and self.emulator.available
        if not wanted and has_mumu:
            wanted = self._boot_emulator()
        online = []
        for attempt in range(10):
            if wanted:
                try:
                    self.adb.connect(wanted)
                except AdbError:
                    pass
            online = self._online(search=not wanted)  # probing all ports takes seconds
            if wanted in online or (not wanted and online):
                break
            # The saved MuMu address is offline: start the emulator
            if attempt == 0 and has_mumu and wanted == "127.0.0.1:16384":
                wanted = self._boot_emulator()
            self._wait(3)
        if not wanted and online:
            wanted = online[0]
        if wanted not in online:
            raise BotError("The device is not online. Start the emulator or pick another device in Settings.")
        self.adb.serial = wanted
        self.log(f"Connected to {wanted}.", "good")

    def _start_game(self) -> None:
        self.status = "Looking at the screen…"
        image = self.adb.screenshot()
        height, width = image.shape[:2]
        if width > height and screen_mod.Screen(image, self.ocr).home():
            self.size = (width, height)
            self.log("Village found.", "good")
            return
        self._capture("start", screen_mod.Screen(image, self.ocr))
        self.status = "Starting game…"
        self.log("Opening Clash of Clans…")
        self.adb.launch_game()
        for _ in range(30):
            image = self.adb.screenshot()
            height, width = image.shape[:2]
            if width > height:
                break
            self._wait(3)
        else:
            raise BotError("The emulator must run in landscape (1600×900).")
        self.size = (width, height)
        if not 1.7 <= width / height <= 1.85:
            self.log(f"Resolution {width}×{height} is not 16:9. Set the emulator to 1600×900.", "warn")
        self.status = "Loading text recognition…"
        self.ocr.read(np.zeros((120, 320, 3), np.uint8))

    def _zoom_out(self) -> None:
        if not self.adb.zoom_out(self.size):
            self._warn_once("zoom", "This emulator does not accept the zoom gesture. Zoom out once by hand.")
        self._wait(0.4)

    # ---------- main cycle ----------
    def _cycle(self, settings) -> None:
        shot = self._go_home()
        if not self._zoomed:
            self._zoom_out()
            self._zoomed = True
            shot = self._go_home()
        if self.on_player:
            name = shot.player_name()
            if name:
                self.on_player(name)
                self.on_player = None
        self._check_storage(shot, settings)
        if settings["donate"]:
            self._donate()
        self._attack(settings)

    def _go_home(self):
        self.status = "Going to the village…"
        unknown = loading = relaunches = 0
        for _ in range(300):
            shot = self._shot()
            if shot.home(thorough=unknown >= 2):
                self._reward_stuck = False
                return shot
            if unknown < 2:  # screens fade in and out: look again quickly before reading everything
                point = shot.button("return_home")
                if point:
                    self._tap(point, 0.8)
                    unknown = 0
                else:
                    unknown += 1
                    self._wait(0.5)
                continue
            if self._handle_screen(shot):
                unknown = 0
                self._wait(1.0)
                continue
            if shot.contains_word(("loading",)) and loading < 90:
                loading += 1
                self.status = "Game is loading…"
                self._wait(1.5)
                continue
            unknown += 1
            if unknown == 4:
                self._capture("unrecognised", shot)
            if unknown == 6:
                self.adb.launch_game()
                self._wait(4)
            elif unknown in (12, 17, 22):
                self._dismiss(shot)      # closes open windows
            elif unknown == 26:
                self._tap(shot.px(layout.POINTS["close_window"]))
            elif unknown >= 30:
                relaunches += 1
                if relaunches > 2:
                    break
                self.log("Village not recognised, restarting the game.", "warn")
                self.adb.stop_game()
                self._wait(2)
                self.adb.launch_game()
                self._wait(20)
                unknown = loading = 0
            self._wait(1.0)
        raise BotError("The village screen is not recognised. Set the game language to English.")

    def _handle_screen(self, shot) -> bool:
        """Gets rid of known screens on the way home. True if something was done."""
        popup = layout.REGIONS["popup"]
        if shot.contains_word(layout.OTHER_DEVICE_WORDS, popup):
            raise BotError("The account is open on another device. The bot stopped so it does not kick you out.")
        if shot.contains_word(layout.BREAK_WORDS, popup):
            self.log("The game asks for a break. Waiting 6 minutes.", "warn")
            self.status = "Game break…"
            self._wait(360)
            self.adb.launch_game()
            return True
        cancel = shot.button("cancel")
        if cancel:
            self._tap(cancel)
            return True
        if self._collect_rewards(shot):  # before the gem check: a reward may well be gems
            return True
        if shot.shows_gems():
            self._dismiss(shot)
            return True
        if shot.upgrade_panel():  # the builder list, left open
            self._dismiss(shot)
            return True
        name, point = self._find_any(shot, ("reload", "return_home", "okay"))
        if name:
            self._tap(point)
            return True
        if shot.button("find_match") or shot.button("army_attack"):
            self.adb.back()
            return True
        # Still scouting or fighting: leave properly
        point = shot.button("end_battle", True)
        if point:
            self._end_battle(point)
            return True
        return False

    def _end_battle(self, point) -> None:
        """Presses End Battle / Surrender and confirms it."""
        self._tap(point, 0.5)
        for _ in range(5):
            shot = self._shot()
            okay = shot.button("okay")
            if okay and not shot.shows_gems():
                self._tap(okay, 0.5)
                return
            if shot.button("return_home") or shot.home():  # no confirmation needed
                return
            self._wait(0.4)

    def _check_storage(self, shot, settings) -> None:
        if not (settings["stop_full"] or settings["walls"]):
            return
        values = shot.storage()
        if values is None:
            self._warn_once("storage", "The storage amounts at the top right cannot be read.")
            return
        capacity = settings["max_storage"]
        if settings["walls"] and max(values) < capacity * WALL_TRIGGER:
            self._warn_once("walls_wait", f"Walls start once gold or elixir reaches "
                            f"{notify.short(capacity * WALL_TRIGGER)} (half of Max Storage Capacity). Now: "
                            f"{notify.short(values[0])} gold, {notify.short(values[1])} elixir.", "info")
        elif settings["walls"]:
            if self._wall_pause:
                self._wall_pause -= 1
            elif self._upgrade_walls(settings):
                home = self._go_home()
                values = home.storage() or values
                self._zoom_out()  # the camera moved to the walls
        if settings["stop_full"] and min(values) >= capacity * 0.98:
            raise Done("Storages are full.")

    # ---------- attacking ----------
    def _attack(self, settings) -> None:
        self.status = "Opening attack menu…"
        point = self._shot().home()
        if not point:
            return
        self._tap(point, 0.5)
        shot, name, point = self._wait_for(("find_match", "next", "army_attack"), 12, rewards=True)
        if name == "find_match":
            claim = shot.button("claim")  # a finished star bonus can wait in the attack menu
            if claim:
                self.log("Claiming a reward in the attack menu.", "good")
                self._tap(claim, 1.0)
                shot, name, point = self._wait_for(("find_match",), 12, rewards=True)
        if name == "find_match":
            self._tap(point, 0.6)
            shot, name, point = self._wait_for(("next", "army_attack"), 30, rewards=True)
        if name == "reward":
            return  # back to the village and start again
        if name == "army_attack":
            self._tap(point, 0.8)
            shot, name, point = self._wait_for(("next",), 60)
        if name != "next":
            self.failures += 1
            self.log("No opponent screen reached, trying again.", "warn")
            return
        found = self._search(shot, settings)
        if found is not None:
            self._fight(found, settings)

    def _search(self, shot, settings):
        """Returns the loot of an opponent worth attacking, or None."""
        searches = unreadable = 0
        while True:
            self.status = f"Searching opponent {searches + 1}…"
            self._wait(0.3)
            shot = self._shot()
            loot = shot.loot()
            if loot is None:
                self._wait(0.8)
                shot = self._shot()
                loot = shot.loot()
            if loot is None:
                unreadable += 1
                self.log("The loot cannot be read.", "warn")
                if unreadable >= 3:
                    leave = shot.button("end_battle", True)
                    if leave:
                        self._end_battle(leave)
                    raise BotError("The loot cannot be read. Check that the resolution is 1600×900.")
            else:
                unreadable = 0
                good = min(loot[0], loot[1]) >= settings["min_loot"]
                self.log(f"Opponent: {notify.short(loot[0])} gold, {notify.short(loot[1])} elixir"
                         + (" → attacking" if good else " → next"), "good" if good else "info")
                if good:
                    return loot
            searches += 1
            self.stats.add(searches=1)
            point = shot.button("next", True)
            if not point:
                shot, _, point = self._wait_for(("next",), 8)
            if searches >= MAX_SEARCHES or not point:
                if searches >= MAX_SEARCHES:
                    self.log(f"No match after {searches} villages. Lower the minimum loot if this repeats.", "warn")
                    self.failures += 1
                else:
                    self._capture("no_next", shot)
                    self.log("The Next button was not found, leaving the search.", "warn")
                leave = shot.button("end_battle", True)
                if leave:
                    self._end_battle(leave)
                return None
            self._tap(point)
            self._wait_gone("next", 6)
            shot, name, _ = self._wait_for(("next",), 45)
            if name != "next":
                self.failures += 1
                self.log("No new opponent was found.", "warn")
                return None

    def _detect_slots(self, wanted):
        """The troop bar. It may still be sliding in or a counter may be hidden, so look several times."""
        for attempt in range(TROOP_LOOKS):
            shot = self._shot()
            slots = army.assign_roles(shot, army.detect_slots(shot))
            troops = [s for s in slots if s.role in wanted and s.count]
            if troops:
                break
            if attempt + 1 < TROOP_LOOKS:
                self._wait(1.2)
        return shot, slots, troops

    def _fight(self, loot, settings) -> None:
        self.status = "Zooming out…"
        self._zoom_out()
        self.status = "Deploying troops…"
        wanted = ("troop", "event") if settings["event_troops"] else ("troop",)
        shot, slots, troops = self._detect_slots(wanted)
        if not troops:
            self.failures += 1
            self._capture("no_troops", shot)
            seen = ", ".join(f"{s.role} x{s.count}" if s.count else s.role for s in slots) or "no cards"
            self.log(f"No troops found in the troop bar ({seen}). Leaving the battle.", "warn")
            leave = shot.button("end_battle", True)
            if leave:
                self._end_battle(leave)
            return
        if not settings["event_troops"] and any(s.role == "event" for s in slots):
            self.log("Event troops are left out (switched off).")
        loot_side = self._loot_side(shot) if settings["style"] == "loot" else None
        sides = army.choose_sides(settings["style"], settings["army"], self.rng, loot_side)
        span = army.line_span(settings["army"])
        self.log("Deploying from: " + ", ".join(SIDE_NAMES[s] for s in sides))
        wardens = {s.index for s in slots if s.role == "hero" and army.is_warden(shot.image, s.left, s.right)}
        started = self.clock()
        outward = 0.0
        for slot in troops:
            outward = self._deploy(shot, slot, sides, span, outward)

        if settings["siege"]:
            middle = shot.px(army.line_points(sides[:1], 3, outward)[1])
            for slot in (s for s in slots if s.role == "siege"):
                self._tap((slot.x, slot.y), 0.15)
                self._tap(middle, 0.15)
        heroes = []
        if settings["heroes"]:
            heroes = [s for s in slots if s.role == "hero" and self._deploy_hero(shot, s, sides, outward)]
        abilities = self._plan_abilities(heroes, wardens)
        self.log(f"Army deployed after {self.clock() - started:.0f} s.")

        spells = army.choose_spells(shot.image, slots, settings["spell"])
        waves = []
        if spells:
            self.status = "Casting spells…"
            self._wait(max(0.0, SPELL_DELAY - (self.clock() - started)))
            self._capture("last_deploy", self._shot())
            first, second = [], []
            for slot in spells:
                points = [shot.px(p) for p in army.spell_points(sides, min(slot.count, 11))]
                half = (len(points) + 1) // 2
                first.append((slot, points[:half]))
                second.append((slot, points[half:]))
            self._cast(first)
            # The second wave lands deeper, when the troops have moved on
            waves.append((self.clock() + SPELL_WAVE_GAP, [w for w in second if w[1]], ""))
        else:
            if settings["spell"] != "none":
                self._warn_once("spells", "No spells found in the army.")
            self._capture("last_deploy", self._shot())
        self._watch_battle(loot, sorted(abilities + waves, key=lambda entry: entry[0]), started)

    def _loot_side(self, shot):
        """The edge closest to the opponent's gold and elixir storages, or None."""
        try:
            self._finder = self._finder or storages.Finder()
            found = self._finder.find(shot.image)
        except Exception as exc:  # a missing or broken model must not cost the attack
            self._warn_once("finder", f"Storage recognition is not available: {exc}")
            return None
        side = storages.best_side(found)
        if self.on_capture:
            try:
                self.on_capture("last_loot", storages.mark(shot.image, found, side))
            except OSError:
                pass
        if side:
            gold = sum(storage.kind == "gold" for storage in found)
            self.log(f"Most loot near {SIDE_NAMES[side]} ({gold} gold and {len(found) - gold} elixir "
                     "storages recognised).", "good")
        else:
            self.log("Storages not recognised on this base, using a random side.", "warn")
        return side

    def _deploy(self, shot, slot, sides, span, outward: float = 0.0) -> float:
        """Places all troops of one card, spread evenly. Returns how far outwards it had to go."""
        remaining = slot.count
        step = LINE_STEPS.index(outward) if outward in LINE_STEPS else 0
        for _ in range(10):
            self._tap((slot.x, slot.y), TAP_PAUSE)
            points = [shot.px(p) for p in army.line_points(sides, min(remaining, 40), LINE_STEPS[step], span)]
            for first in range(0, len(points), 8):
                if first:
                    self._wait(BATCH_PAUSE)
                self._check_stop()
                self.adb.tap_many(points[first:first + 8])
            self._wait(COUNT_PAUSE)
            left = army.card_count(self._shot(), slot.left, slot.right)
            if left is None:  # look once more before believing it
                self._wait(0.4)
                left = army.card_count(self._shot(), slot.left, slot.right)
            if not left:  # counter gone or x0: everything is deployed
                return LINE_STEPS[step]
            if left >= remaining:
                # Nothing arrived: red line or edge of the map, try a line next to this one
                if step + 1 >= len(LINE_STEPS):
                    break
                step += 1
            remaining = left
        self.log(f"{remaining} troops could not be deployed.", "warn")
        return LINE_STEPS[step]

    def _deploy_hero(self, shot, slot, sides, outward: float) -> bool:
        """Places one hero. The card is only tapped again while it is clearly still waiting,
        because a second tap on a placed hero uses up the ability."""
        if army.hero_deployed(shot.image, slot.left, slot.right):
            return False  # already grey before the battle: the hero is not available
        for extra in HERO_STEPS:
            self._tap((slot.x, slot.y), 0.15)
            self._tap(shot.px(army.line_points(sides[:1], 3, outward + extra)[1]), 0.5)
            for _ in range(2):
                if army.hero_deployed(self._shot().image, slot.left, slot.right):
                    return True
                self._wait(0.4)
        self.log("A hero could not be deployed.", "warn")
        return False

    def _plan_abilities(self, heroes, wardens) -> list:
        """[(time, cards, log text)]: all other heroes first, the Grand Warden afterwards."""
        now = self.clock()
        others = [s for s in heroes if s.index not in wardens]
        warden = [s for s in heroes if s.index in wardens]
        plan = []
        if others:
            plan.append((now + ABILITY_DELAY, others, "Hero abilities activated."))
        if warden:
            plan.append((now + ABILITY_DELAY + WARDEN_GAP, warden, "Grand Warden ability activated."))
        return plan

    def _cast(self, wave: list) -> None:
        """wave: [(spell card, positions)]"""
        for slot, points in wave:
            self._tap((slot.x, slot.y), TAP_PAUSE)
            for point in points:
                self._tap(point, TAP_PAUSE)

    def _use_planned(self, plan: list) -> None:
        """Runs what is due: hero abilities (cards with a log text) and later spell waves."""
        while plan and self.clock() >= plan[0][0]:
            _, items, text = plan.pop(0)
            if not text:
                self._cast(items)
                continue
            for slot in items:
                self._tap((slot.x, slot.y), 0.2)
            self.log(text)

    def _watch_battle(self, loot, plan, started) -> None:
        self.status = "Battle in progress…"
        total = loot[0] + loot[1]
        remaining = total
        last_loot = loot
        progress = self.clock()
        lost = nearly_empty = 0
        self._counted = False
        try:
            while True:
                self._wait(BATTLE_LOOK)
                shot = self._shot()
                leave = shot.button("end_battle", thorough=lost >= 2)
                if not leave:
                    if shot.button("return_home"):
                        break
                    lost += 1
                    if lost >= 8:
                        self.failures += 1
                        self.log("The battle screen disappeared.", "warn")
                        return
                    continue
                lost = 0
                self._use_planned(plan)  # only while the battle is on screen
                now_loot = shot.loot()
                if now_loot and now_loot[0] + now_loot[1] <= total * 1.02:  # more than at the start: misread
                    left = now_loot[0] + now_loot[1]
                    if left <= remaining - max(1000, total // 200):
                        progress = self.clock()
                        remaining, last_loot = left, now_loot
                    elif left > remaining:  # an earlier picture was misread
                        remaining, last_loot = left, now_loot
                    nearly_empty = nearly_empty + 1 if left <= total * LOOT_DONE else 0
                elapsed = self.clock() - started
                reason = None
                if elapsed >= MAX_BATTLE:
                    reason = "Time limit reached"
                elif nearly_empty >= 2 and elapsed >= LOOT_DONE_AFTER:
                    reason = "Almost all loot taken"
                elif elapsed >= MIN_BATTLE and self.clock() - progress >= STALE_AFTER:
                    reason = "No more loot coming in"
                if reason:
                    self.log(f"{reason}, ending the battle after {elapsed:.0f} s.")
                    self._capture("last_battle_end", shot)
                    self._end_battle(leave)
                    shot, name, _ = self._wait_for(("return_home",), 25)
                    if not name:
                        self.failures += 1
                        return
                    break
            self._finish(loot, last_loot)
        except Stop:
            # Stopped in the middle of a battle: count what is already taken
            gold, elixir = (max(0, a - b) for a, b in zip(loot[:2], last_loot[:2]))
            if not self._counted and gold + elixir:
                self.stats.add(gold=gold, elixir=elixir, attacks=1)
                self.log(f"Stopped during a battle: +{notify.short(gold)} gold, "
                         f"+{notify.short(elixir)} elixir so far.", "good")
            raise

    def _finish(self, first, last) -> None:
        self.status = "Reading result…"
        self._wait(1.5)  # the numbers count up
        shot = self._shot()
        result = shot.result_loot()
        for _ in range(4):
            self._wait(0.6)
            shot = self._shot()
            again = shot.result_loot()
            settled = again == result and again is not None
            result = again
            if settled:
                break
        self._capture("last_result", shot)
        taken = tuple(max(0, a - b) for a, b in zip(first, last))  # what disappeared from the opponent
        if result is None or max(result) > 40_000_000:
            result = taken
        # A result with fewer digits than what was seen leaving the opponent is a misreading
        gold, elixir = (t if len(str(r)) < len(str(t)) else r for r, t in zip(result[:2], taken[:2]))
        dark = result[2]
        self.stats.add(gold=gold, elixir=elixir, dark=dark, attacks=1)
        self._counted = True
        self.failures = 0
        self.log(f"Attack finished: +{notify.short(gold)} gold, +{notify.short(elixir)} elixir", "good")
        if self.stats.session["attacks"] % 10 == 0:
            self._report("RaidPilot status")
        point = shot.button("return_home")
        if point:
            self._tap(point, 0.8)

    # ---------- walls ----------
    def _upgrade_walls(self, settings) -> bool:
        """Builder list -> a wall line -> "Upgrade" (gold or elixir) -> "Confirm", wall after wall,
        until no wall can be paid any more. Gem offers are closed, never confirmed.
        True if the builder list was opened."""
        shot = self._go_home()
        storage = shot.storage()
        if not storage or max(storage) < settings["max_storage"] * WALL_TRIGGER:
            return False
        builder = shot.builder_button()
        if builder and builder[0] == 0:
            self._warn_once("builder", "No free builder: the game needs one for walls, skipping for now.")
            return False
        self.status = "Upgrading walls…"
        self.log(f"Storage over half full ({notify.short(storage[0])} gold, {notify.short(storage[1])} "
                 "elixir): upgrading walls.")
        money = {"gold": storage[0], "elixir": storage[1]}
        done, problem, skipped = 0, "No affordable wall was found in the builder list.", set()
        while done < WALLS_PER_VISIT and len(skipped) < 4:
            if done and max(money.values()) < WALL_FLOOR:
                break  # too little left for another wall
            entry = self._find_wall_entry(money, skipped)
            if entry is None:
                break
            problem = self._buy_wall(entry, money)
            if problem == NOT_ENOUGH:
                skipped.add(entry[0])  # try a cheaper wall
                continue
            if problem:
                break
            done += 1
        self._close_builder_list()
        if done:
            self.log(f"Walls finished: {done} upgraded. Back to attacking.", "good")
        else:
            self._wall_pause = WALL_PAUSE  # do not lose time on it before every attack
            self._warn_once("walls", problem or "No wall could be upgraded.")
        return True

    def _open_builder_list(self):
        """The picture with the open builder list, or None."""
        shot = self._shot()
        if shot.upgrade_panel():
            return shot
        if not shot.home():
            shot = self._go_home()
        builder = shot.builder_button()
        self._tap(builder[1] if builder else shot.px(layout.POINTS["builder_menu"]), 1.0)
        for _ in range(3):
            shot = self._shot()
            if shot.upgrade_panel():
                return shot
            self._wait(0.6)
        self._capture("walls_no_list", shot)
        return None

    def _find_wall_entry(self, money, skipped=()):
        """Scrolls down the builder list to the first wall that can be paid: (price, position)."""
        shot = self._open_builder_list()
        if shot is None:
            return None
        previous, unchanged = None, 0
        seen, rewound = False, False
        for _ in range(2 * WALL_SCROLLS):
            entries = shot.wall_entries()
            seen = seen or bool(entries)
            for price, point in entries:
                if price not in skipped and (price is None or price <= max(money.values())):
                    return price, point
            panel = shot.upgrade_panel()
            if not panel:
                break
            x = panel[0] / shot.width
            picture = shot.crop((x - 0.12, 0.15, x + 0.12, 0.85))[0][::6, ::6].astype(np.int16)
            if previous is not None and np.abs(picture - previous).mean() < 1.5:
                unchanged += 1
            else:
                unchanged = 0
            previous = picture
            if unchanged >= 2:  # the end of the list
                if seen or rewound:
                    break
                # The list was not at its top when the search began: go up and look through it again
                rewound, previous, unchanged = True, None, 0
                for _ in range(8):
                    self.adb.swipe(*shot.px((x, 0.30)), *shot.px((x, 0.80)), 200)
                    self._wait(0.4)
            else:
                # A slow swipe: a fast one would fling the list past the walls
                self.adb.swipe(*shot.px((x, 0.74)), *shot.px((x, 0.42)), 700)
                self._wait(0.7)
            shot = self._shot()
        self._capture("walls_not_found", shot)
        return None

    def _buy_wall(self, entry, money) -> str:
        """Upgrades the wall of a list line. Returns '' on success, otherwise what went wrong."""
        price, point = entry
        self._tap(point, 1.2)
        tried = set()
        for _ in range(3):
            shot = self._shot()
            buttons = shot.upgrade_buttons()
            if not buttons:
                self._wait(0.8)
                shot = self._shot()
                buttons = shot.upgrade_buttons()
            if not buttons:
                if tried:
                    break
                self._capture("walls_2_selected", shot)
                return "No upgrade button was found for the wall."
            # The left button costs gold, the right one elixir. Take the fuller storage first.
            options = [(name, button) for name, button in zip(("gold", "elixir"), buttons)
                       if name not in tried and (price is None or money[name] >= price)]
            if not options:
                break
            name, button = max(options, key=lambda option: money[option[0]])
            tried.add(name)
            self._tap(button, 1.2)
            shot = self._shot()
            dialog = shot.wall_dialog()
            if not dialog:
                self._wait(0.8)
                shot = self._shot()
                dialog = shot.wall_dialog()
            if not dialog:
                self._capture("walls_3_confirm", shot)
                self._dismiss(shot)
                return "The wall window did not open (nothing was bought)."
            confirm, cost, currency = dialog
            currency = currency or name
            cost = cost or price
            tried.add(currency)
            if shot.shows_gems() or (cost and money[currency] < cost):
                self._dismiss(shot)
                continue
            self._capture("walls_3_confirm", shot)
            self._tap(confirm, 1.5)
            shot = self._shot()
            if shot.shows_gems():  # "Need more gold?": close the offer and the window
                self._dismiss(shot)
                shot = self._shot()
                if shot.wall_dialog():
                    self._dismiss(shot)
                money[currency] = min(money[currency], (cost or 1) - 1)
                continue
            if shot.wall_dialog():
                self._capture("walls_4_stuck", shot)
                self._dismiss(shot)
                return "The wall upgrade did not go through."
            money[currency] = max(0, money[currency] - (cost or 0))
            self.stats.add(walls=1)
            self.log(f"Wall upgraded for {notify.short(cost) if cost else '?'} {currency}.", "good")
            return ""
        return NOT_ENOUGH

    def _close_builder_list(self) -> None:
        """Closes whatever the wall upgrade left open."""
        for attempt in range(5):
            shot = self._shot()
            if not (shot.upgrade_panel() or shot.wall_dialog()):
                return
            if attempt < 3:
                self._dismiss(shot)
            else:  # the X was not found or did not react
                self._tap(shot.px(layout.POINTS["list_close"]), 0.8)
        self._capture("walls_stuck", self._shot())

    # ---------- donations ----------
    def _donate(self) -> None:
        self.status = "Donating troops…"
        shot = self._shot()
        self._tap(shot.px(layout.POINTS["chat_open"]), 1.8)
        donated = 0
        for _ in range(3):
            shot = self._shot()
            point = shot.button("donate")
            if not point:
                break
            self._tap(point, 1.2)
            shot = self._shot()
            if shot.shows_gems():
                self.adb.back()
                break
            # Only cards with an own troop counter are tapped, never gem offers
            cards = [w for w in shot.words(layout.REGIONS["donate_popup"])
                     if re.fullmatch(r"[x×X]\s?\d{1,3}", w.text.strip())]
            if not cards:
                self.adb.back()
                break
            card = cards[0]
            target = (int(card.center[0]), int(card.center[1] + 0.05 * shot.height))
            for _tap in range(5):
                self._tap(target, 0.35)
            donated += 1
            self.adb.back()
            self._wait(1.0)
        shot = self._shot()
        if not shot.home():
            self._tap(shot.px(layout.POINTS["chat_close"]), 1.0)
        if donated:
            self.log(f"Answered {donated} donation request(s).", "good")
