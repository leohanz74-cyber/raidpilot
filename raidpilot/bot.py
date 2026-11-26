"""The automation: emulator -> game -> own village -> search -> attack -> back home.
Everything happens through screenshots and touch input."""
import random
import re
import threading
import time
import traceback

import numpy as np

from . import army, layout, notify, screen as screen_mod
from .adb import AdbError
from .mumu import MumuError

MAX_BATTLE = 75           # seconds after the first troop until a battle is ended at the latest
MIN_BATTLE = 40           # never end for lack of loot before this
STALE_AFTER = 18          # seconds without new loot
LOOT_DONE = 0.05          # end once only this share of the loot is left ...
LOOT_DONE_AFTER = 20      # ... and at least this many seconds have passed
SPELL_DELAY = 7
ABILITY_DELAY = 12
MAX_SEARCHES = 60
UNKNOWN_RELAUNCH = 16     # unknown pictures in a row until the game is restarted
BOOT_TIMEOUT = 240
WALLS_PER_VISIT = 5


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
        adb_errors = 0
        reason = "Stopped"
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
            self.stats.stop()
            self.status = "Error" if self.last_error else "Ready"
            self.log("Bot stopped.")
            self._report(f"RaidPilot stopped: {reason}")

    # ---------- helpers ----------
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

    def _wait_for(self, names, timeout: float, interval: float = 0.3):
        """Waits for one of the buttons. Handles dialogs that can appear while an attack starts."""
        began = self.clock()
        while True:
            shot = self._shot()
            waited = self.clock() - began
            # Reading the whole screen is slow: only do it when the button takes unusually long
            name, point = self._find_any(shot, names, waited >= 4)
            if name:
                return shot, name, point
            if waited >= 2.5:
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
            self._wait(0.25)
            if not self._shot().button(name):
                return True
        return False

    def _warn_once(self, key: str, text: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.log(text, "warn")

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
            if unknown == 6:
                self.adb.launch_game()
                self._wait(4)
            elif unknown in (12, 17, 22):
                self.adb.back()          # closes open windows
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
        if shot.shows_gems():
            self.adb.back()
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
        if settings["walls"] and max(values) >= capacity * 0.9:
            self._upgrade_walls(settings)
            values = self._go_home().storage() or values
        if settings["stop_full"] and min(values) >= capacity * 0.98:
            raise Done("Storages are full.")

    # ---------- attacking ----------
    def _attack(self, settings) -> None:
        self.status = "Opening attack menu…"
        point = self._shot().home()
        if not point:
            return
        self._tap(point, 0.5)
        shot, name, point = self._wait_for(("find_match", "next", "army_attack"), 12)
        if name == "find_match":
            self._tap(point, 0.6)
            shot, name, point = self._wait_for(("next", "army_attack"), 30)
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
                good = loot[0] + loot[1] >= settings["min_loot"]
                self.log(f"Opponent: {notify.short(loot[0])} gold, {notify.short(loot[1])} elixir"
                         + (" → attacking" if good else " → next"), "good" if good else "info")
                if good:
                    return loot
            searches += 1
            self.stats.add(searches=1)
            point = shot.button("next", True)
            if searches >= MAX_SEARCHES or not point:
                if searches >= MAX_SEARCHES:
                    self.log(f"No match after {searches} villages. Lower the minimum loot if this repeats.", "warn")
                    self.failures += 1
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

    def _detect_slots(self):
        shot = self._shot()
        slots = army.detect_slots(shot)
        if not any(s.count for s in slots):  # the bar may still be sliding in
            self._wait(1.0)
            shot = self._shot()
            slots = army.detect_slots(shot)
        return shot, army.assign_roles(shot, slots)

    def _fight(self, loot, settings) -> None:
        self.status = "Zooming out…"
        self._zoom_out()
        self.status = "Deploying troops…"
        shot, slots = self._detect_slots()
        wanted = ("troop", "event") if settings["event_troops"] else ("troop",)
        troops = [s for s in slots if s.role in wanted and s.count]
        if not troops:
            self.failures += 1
            self.log("No troops found in the troop bar. Leaving the battle.", "warn")
            leave = shot.button("end_battle", True)
            if leave:
                self._end_battle(leave)
            return
        if not settings["event_troops"] and any(s.role == "event" for s in slots):
            self.log("Event troops are left out (switched off).")
        sides = army.choose_sides(settings["style"], settings["army"], self.rng)
        span = army.line_span(settings["army"])
        names = {"tl": "Top Left", "tr": "Top Right", "bl": "Bottom Left", "br": "Bottom Right"}
        self.log("Deploying from: " + ", ".join(names[s] for s in sides))
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
        self.log(f"Army deployed after {self.clock() - started:.0f} s.")

        spells = army.choose_spells(shot.image, slots, settings["spell"])
        if spells:
            self.status = "Casting spells…"
            self._wait(max(0.0, SPELL_DELAY - (self.clock() - started)))
            for slot in spells:
                self._tap((slot.x, slot.y), 0.15)
                for rel in army.spell_points(sides, min(slot.count, 11)):
                    self._tap(shot.px(rel), 0.15)
        elif settings["spell"] != "none":
            self._warn_once("spells", "No spells found in the army.")
        self._capture("last_deploy", self._shot())
        self._watch_battle(loot, heroes, started)

    def _deploy(self, shot, slot, sides, span, outward: float = 0.0) -> float:
        """Places all troops of one card, spread evenly. Returns how far outwards it had to go."""
        remaining = slot.count
        stuck = 0
        for _ in range(10):
            self._tap((slot.x, slot.y), 0.15)
            points = [shot.px(p) for p in army.line_points(sides, min(remaining, 40), outward, span)]
            for first in range(0, len(points), 8):
                self._check_stop()
                self.adb.tap_many(points[first:first + 8])
            self._wait(0.35)
            left = army.card_count(self._shot(), slot.left, slot.right)
            if left is None:  # look once more before believing it
                self._wait(0.4)
                left = army.card_count(self._shot(), slot.left, slot.right)
            if not left:  # counter gone or x0: everything is deployed
                return outward
            if left >= remaining:
                # Nothing arrived: probably inside the red line, move further out
                stuck += 1
                outward += 0.025
                if stuck >= 4:
                    break
            remaining = left
        self.log(f"{remaining} troops could not be deployed.", "warn")
        return outward

    def _deploy_hero(self, shot, slot, sides, outward: float) -> bool:
        for extra in (0.0, 0.04, 0.09):
            self._tap((slot.x, slot.y), 0.15)
            self._tap(shot.px(army.line_points(sides[:1], 3, outward + extra)[1]), 0.5)
            if army.hero_deployed(self._shot().image, slot.left, slot.right):
                return True
        self.log("A hero could not be deployed.", "warn")
        return False

    def _watch_battle(self, loot, heroes, started) -> None:
        self.status = "Battle in progress…"
        total = loot[0] + loot[1]
        remaining = total
        last_loot = loot
        progress = self.clock()
        ability_used = not heroes
        lost = nearly_empty = 0
        while True:
            self._wait(1.0)
            if not ability_used and self.clock() - started >= ABILITY_DELAY:
                for slot in heroes:
                    self._tap((slot.x, slot.y), 0.15)
                ability_used = True
            shot = self._shot()
            leave = shot.button("end_battle", thorough=lost >= 2)
            if not leave:
                if shot.button("return_home"):
                    break
                lost += 1
                if lost >= 12:
                    self.failures += 1
                    self.log("The battle screen disappeared.", "warn")
                    return
                continue
            lost = 0
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
        if result is None or max(result) > 40_000_000:
            # Fallback: what disappeared from the opponent
            result = tuple(max(0, a - b) for a, b in zip(first, last))
        gold, elixir, dark = result
        self.stats.add(gold=gold, elixir=elixir, dark=dark, attacks=1)
        self.failures = 0
        self.log(f"Attack finished: +{notify.short(gold)} gold, +{notify.short(elixir)} elixir", "good")
        if self.stats.session["attacks"] % 10 == 0:
            self._report("RaidPilot status")
        point = shot.button("return_home")
        if point:
            self._tap(point, 0.8)

    # ---------- walls ----------
    def _find_wall_entry(self):
        for _ in range(6):
            shot = self._shot()
            for word in screen_mod.join_lines(shot.words(layout.REGIONS["builder_list"])):
                if any(w in screen_mod.normalize(word.text) for w in layout.WALL_WORDS):
                    return shot, word
            self.adb.swipe(*shot.px((0.55, 0.65)), *shot.px((0.55, 0.30)), 500)
            self._wait(1.0)
        return shot, None

    def _upgrade_walls(self, settings) -> None:
        for _ in range(WALLS_PER_VISIT):
            shot = self._go_home()
            before = shot.storage()
            if not before or max(before) < settings["max_storage"] * 0.75:
                return
            if shot.free_builders() == 0:
                self._warn_once("builder", "No free builder, walls are skipped for now.")
                return
            self.status = "Upgrading walls…"
            self._tap(shot.px(layout.POINTS["builder_menu"]), 1.5)
            shot, entry = self._find_wall_entry()
            if not entry:
                self.adb.back()
                self._warn_once("walls", "No wall was found in the builder list.")
                return
            self._tap(tuple(int(v) for v in entry.center), 1.8)
            shot = self._shot()
            region = layout.BUTTONS["upgrade"][0]
            buttons = sorted((w for w in shot.words(region) if screen_mod.normalize(w.text) == "upgrade"),
                             key=lambda w: w.x)
            if not buttons:
                self.adb.back()
                self._warn_once("walls", "No upgrade button was found for the wall.")
                return
            # With two buttons the left one costs gold, the right one elixir
            choice = buttons[-1] if len(buttons) > 1 and before[1] > before[0] else buttons[0]
            self._tap(tuple(int(v) for v in choice.center), 1.5)
            shot = self._shot()
            confirm = None if shot.shows_gems() else shot.button("confirm")
            if not confirm:
                self.adb.back()
                self._warn_once("walls", "The wall upgrade was not confirmed (nothing was bought).")
                return
            self._tap(confirm, 1.8)
            if self._shot().shows_gems():
                self.adb.back()
                return
            after = self._go_home().storage()
            if after and (after[0] < before[0] or after[1] < before[1]):
                self.stats.add(walls=1)
                self.log("Wall upgraded.", "good")
            else:
                self._warn_once("walls", "The wall upgrade did not go through.")
                return

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
