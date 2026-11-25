"""Der Ablauf: Dorf -> Gegner suchen -> Truppen absetzen -> zurueck. Alles ueber Bildschirm + Tippen."""
import random
import threading
import time
import traceback

from . import army, layout, notify, screen as screen_mod
from .adb import AdbError

MAX_BATTLE = 215          # Sekunden, danach wird der Kampf beendet
UNKNOWN_RELAUNCH = 12     # unbekannte Bilder in Folge bis zum Neustart des Spiels


class Stop(Exception):
    """Der Nutzer hat gestoppt."""


class Done(Exception):
    """Ziel erreicht, sauber beenden."""


class BotError(Exception):
    """Weitermachen waere sinnlos oder riskant."""


class Bot:
    def __init__(self, adb, ocr, get_settings, stats, log, clock=time.monotonic, sleep=None, rng=None):
        self.adb = adb
        self.ocr = ocr
        self.get_settings = get_settings
        self.stats = stats
        self.log = log
        self.clock = clock
        self._sleep = sleep
        self.rng = rng or random.Random()
        self._stop = threading.Event()
        self._thread = None
        self.status = "Bereit"
        self.last_error = ""

    # ---------- Steuerung ----------
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
            self.status = "Stoppe…"
        self._stop.set()

    def join(self, timeout=None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def run(self) -> None:
        """Blockierende Hauptschleife (im Test direkt aufrufbar)."""
        self.stats.start()
        self.failures = 0
        self._warned = set()
        adb_errors = 0
        reason = "Gestoppt"
        try:
            self._prepare()
            while True:
                self._check_stop()
                settings = self.get_settings()
                limit = settings["max_attacks"]
                if limit and self.stats.session["attacks"] >= limit:
                    raise Done(f"{limit} Angriffe erledigt.")
                try:
                    self._cycle(settings)
                    adb_errors = 0
                except AdbError as exc:
                    adb_errors += 1
                    self.log(f"Verbindung: {exc}", "warn")
                    if adb_errors >= 5:
                        raise BotError("Die Verbindung zum Emulator ist weg.") from exc
                    self._wait(4)
                if self.failures >= 5:
                    raise BotError("Fünfmal hintereinander kein Angriff möglich. Prüfe die Einrichtung (Erkennung testen).")
        except Stop:
            pass
        except Done as exc:
            reason = str(exc)
            self.log(reason, "good")
        except (BotError, AdbError) as exc:
            reason = self.last_error = str(exc)
            self.log(reason, "error")
        except Exception as exc:  # unerwartet: melden statt still zu sterben
            reason = self.last_error = f"Unerwarteter Fehler: {exc}"
            self.log(reason, "error")
            self.log(traceback.format_exc(), "error")
        finally:
            self.stats.stop()
            self.status = "Fehler" if self.last_error else "Bereit"
            self.log("Bot beendet.")
            self._report(f"RaidPilot beendet: {reason}")

    # ---------- Hilfen ----------
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
        return screen_mod.Screen(self.adb.screenshot(), self.ocr)

    def _tap(self, point, pause: float = 0.0) -> None:
        self._check_stop()
        self.adb.tap(*point)
        if pause:
            self._wait(pause)

    def _find_any(self, shot, names):
        for name in names:
            point = shot.button(name)
            if point:
                return name, point
        return None, None

    def _wait_for(self, names, timeout: float, interval: float = 0.8):
        end = self.clock() + timeout
        while True:
            shot = self._shot()
            name, point = self._find_any(shot, names)
            if name or self.clock() >= end:
                return shot, name, point
            self._wait(interval)

    def _wait_gone(self, name: str, timeout: float) -> bool:
        end = self.clock() + timeout
        while self.clock() < end:
            self._wait(0.5)
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
        notify.send(url, f"{headline}\nAngriffe: {s['attacks']} · Gold: {notify.short(s['gold'])} · "
                         f"Elixier: {notify.short(s['elixir'])} · Mauern: {s['walls']}", self.log)

    # ---------- Ablauf ----------
    def _prepare(self) -> None:
        self.status = "Verbinde…"
        if not self.adb.serial:
            online = [d for d in self.adb.devices() if d["state"] == "device"]
            if not online:
                raise BotError("Kein Gerät gefunden. Starte den Emulator und drücke in den Einstellungen auf Aktualisieren.")
            self.adb.serial = online[0]["serial"]
        self.log(f"Gerät: {self.adb.serial}")
        image = self.adb.screenshot()
        height, width = image.shape[:2]
        if width <= height:
            self.log("Bild ist hochkant, starte das Spiel…")
            self.adb.launch_game()
            self._wait(8)
            image = self.adb.screenshot()
            height, width = image.shape[:2]
            if width <= height:
                raise BotError("Der Emulator muss im Querformat laufen (empfohlen 1280×720 oder 1600×900).")
        if not 1.65 <= width / height <= 1.9:
            self.log(f"Auflösung {width}×{height} ist nicht 16:9. Stelle den Emulator am besten auf 1280×720.", "warn")
        self.status = "Lade Texterkennung…"
        self.ocr.read(image[:120, :320])

    def _cycle(self, settings) -> None:
        shot = self._go_home()
        self._check_storage(shot, settings)
        if settings["donate"] and settings["mode"] == "home":
            self._donate()
        if settings["mode"] == "builder":
            self._attack_builder(settings)
        else:
            self._attack_home(settings)

    def _go_home(self):
        self.status = "Gehe ins Dorf…"
        unknown = 0
        relaunches = 0
        for _ in range(80):
            shot = self._shot()
            if shot.button("attack_home") and not shot.button("reload"):
                return shot
            if self._handle_screen(shot):
                unknown = 0
                self._wait(2)
                continue
            unknown += 1
            if unknown == 3:
                self.adb.launch_game()
                self._wait(5)
            elif unknown in (6, 9):
                self.adb.back()
            elif unknown >= UNKNOWN_RELAUNCH:
                relaunches += 1
                if relaunches > 2:
                    break
                self.log("Dorf nicht erkannt, starte das Spiel neu.", "warn")
                self.adb.stop_game()
                self._wait(2)
                self.adb.launch_game()
                self._wait(20)
                unknown = 0
            self._wait(2.5)
        raise BotError("Das Dorf wird nicht erkannt. Prüfe unter Einrichtung die Erkennung.")

    def _handle_screen(self, shot) -> bool:
        """Bekannte Zwischenbildschirme wegklicken. True, wenn etwas getan wurde."""
        popup = layout.REGIONS["popup"]
        if shot.contains_word(layout.OTHER_DEVICE_WORDS, popup):
            raise BotError("Du spielst gerade auf einem anderen Gerät. Der Bot hält an.")
        if shot.contains_word(layout.BREAK_WORDS, popup):
            self.log("Das Spiel verlangt eine Pause. Warte 6 Minuten.", "warn")
            self.status = "Spielpause…"
            self._wait(360)
        cancel = shot.find_text(("Cancel", "Abbrechen"), popup)
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
        # Noch im Spaehbildschirm oder Kampf: sauber verlassen
        point = shot.button("end_battle")
        if point:
            self._end_battle(point)
            return True
        return False

    def _end_battle(self, point) -> None:
        self._tap(point, 1.2)
        shot = self._shot()
        okay = shot.button("okay")
        if okay and not shot.shows_gems():
            self._tap(okay, 1.5)

    def _check_storage(self, shot, settings) -> None:
        values = shot.storage()
        if values is None:
            if settings["stop_full"] or settings["walls"]:
                self._warn_once("storage", "Lagerstand oben rechts nicht lesbar.")
            return
        capacity = settings["max_storage"]
        if settings["walls"] and settings["mode"] == "home" and max(values) >= capacity * 0.9:
            self._upgrade_walls(settings)
            values = self._go_home().storage() or values
        if settings["stop_full"] and min(values) >= capacity * 0.98:
            raise Done("Lager sind voll.")

    # ---------- Heimatdorf ----------
    def _attack_home(self, settings) -> None:
        self.status = "Öffne Angriff…"
        shot = self._shot()
        point = shot.button("attack_home")
        if not point:
            return
        self._tap(point, 1.2)
        shot, name, point = self._wait_for(("find_match", "next", "army_attack"), 12)
        if name == "find_match":
            self._tap(point, 1.5)
            shot, name, point = self._wait_for(("next", "army_attack"), 20)
        if name == "army_attack":
            self._tap(point, 2)
            shot, name, point = self._wait_for(("next",), 60)
        if name != "next":
            self.failures += 1
            self.log("Suchbildschirm nicht erreicht, neuer Versuch.", "warn")
            return
        found = self._search(shot, settings)
        if found is None:
            return
        shot, loot = found
        self._fight(shot, loot, settings)

    def _enough(self, loot, settings) -> bool:
        gold, elixir, _ = loot
        if settings["loot_rule"] == "each":
            return gold >= settings["min_loot"] and elixir >= settings["min_loot"]
        return gold + elixir >= settings["min_loot"]

    def _search(self, shot, settings):
        searches = 0
        unreadable = 0
        while True:
            self.status = "Suche Beute…"
            self._wait(1.0)
            shot = self._shot()
            loot = shot.loot()
            if loot is None:
                self._wait(1.0)
                shot = self._shot()
                loot = shot.loot()
            if loot is None:
                unreadable += 1
                self.log("Beute nicht lesbar.", "warn")
                if unreadable >= 3:
                    leave = shot.button("end_battle")
                    if leave:
                        self._end_battle(leave)
                    raise BotError("Die Beute lässt sich nicht lesen. Prüfe die Auflösung (1280×720) und teste die Erkennung.")
            else:
                unreadable = 0
                good = self._enough(loot, settings)
                self.log(f"Gegner: {notify.short(loot[0])} Gold, {notify.short(loot[1])} Elixier"
                         + (" → Angriff" if good else " → weiter"), "good" if good else "info")
                if good:
                    return shot, loot
            searches += 1
            self.stats.add(searches=1)
            point = shot.button("next")
            if searches >= settings["max_searches"] or not point:
                if searches >= settings["max_searches"]:
                    self.log(f"{searches} Dörfer ohne Treffer. Senke die Mindestbeute, wenn das öfter passiert.", "warn")
                    self.failures += 1
                leave = shot.button("end_battle")
                if leave:
                    self._end_battle(leave)
                return None
            self._tap(point)
            self._wait_gone("next", 6)
            shot, name, _ = self._wait_for(("next",), 45)
            if name != "next":
                self.failures += 1
                self.log("Kein neuer Gegner gefunden.", "warn")
                return None

    def _detect_slots(self, shot, settings):
        for attempt in range(3):
            slots = army.detect_slots(shot)
            if slots:
                return shot, army.assign_roles(shot, slots, settings)
            self._wait(1.5)
            shot = self._shot()
        return shot, []

    def _fight(self, shot, loot, settings) -> None:
        self.status = "Setze Truppen ab…"
        shot, slots = self._detect_slots(shot, settings)
        usable = [s for s in slots if s.role == "troop" or (s.role == "event" and settings["event_troops"])]
        if not usable:
            self.failures += 1
            self.log("Keine Truppen in der Leiste erkannt. Kampf wird verlassen.", "warn")
            leave = shot.button("end_battle")
            if leave:
                self._end_battle(leave)
            return
        sides = army.choose_sides(settings["style"], settings["army"], self.rng)
        side_map = layout.sides()
        self.log("Seite: " + ", ".join({"tl": "oben links", "tr": "oben rechts", "bl": "unten links",
                                        "br": "unten rechts"}[s] for s in sides))
        for slot in usable:
            self._deploy_troop(shot, slot, sides, side_map)

        middle = [shot.px(p) for p in army.line_points(side_map, sides[:1], 3)][1]
        if settings["siege"]:
            for slot in (s for s in slots if s.role == "siege"):
                self._tap((slot.x, slot.y), 0.25)
                self._tap(middle, 0.25)
        heroes = [s for s in slots if s.role == "hero"] if settings["heroes"] else []
        for slot in heroes:
            self._tap((slot.x, slot.y), 0.25)
            self._tap(middle, 0.25)
        started = self.clock()

        spells = [s for s in slots if s.role == "spell"] if settings["spell"] != "none" else []
        if spells:
            self.status = "Warte auf Zauber…"
            self._wait(settings["spell_delay"])
            for number, slot in enumerate(spells):
                self._tap((slot.x, slot.y), 0.25)
                amount = min(slot.count or 1, 11)
                # Weitere Zaubersorten etwas tiefer in der Basis setzen
                for rel in army.spell_points(side_map, sides, amount, 0.5 + 0.15 * number):
                    self._tap(shot.px(rel), 0.35)
        self._watch_battle(loot, heroes, started, settings)

    def _count_at(self, shot, slot):
        step = shot.height * army.DEFAULT_STEP
        for x, _, count in army.read_counts(shot):
            if abs(x - slot.x) < step * 0.45:
                return count
        return None

    def _deploy_troop(self, shot, slot, sides, side_map) -> None:
        self._tap((slot.x, slot.y), 0.3)
        remaining = slot.count or 1
        outward = 0.0
        stuck = 0
        for _ in range(10):
            batch = min(remaining, 40)
            for rel in army.line_points(side_map, sides, batch, outward):
                self._tap(shot.px(rel), 0.06)
            if slot.count is None:
                return
            self._wait(0.6)
            left = self._count_at(self._shot(), slot)
            if not left:  # Zaehler weg oder x0: alle abgesetzt
                return
            if left >= remaining:
                # Nichts angekommen: vermutlich innerhalb der roten Linie, weiter nach aussen
                stuck += 1
                outward += 0.045
                if stuck >= 3:
                    break
            remaining = left
        self.log(f"{remaining} Truppen ließen sich nicht absetzen.", "warn")

    def _watch_battle(self, loot, heroes, started, settings) -> None:
        self.status = "Kampf läuft…"
        last_loot = loot
        changed = self.clock()
        ability_used = not heroes or not settings["hero_ability_after"]
        lost = 0
        while True:
            self._wait(2)
            if not ability_used and self.clock() - started >= settings["hero_ability_after"]:
                for slot in heroes:
                    self._tap((slot.x, slot.y), 0.2)
                ability_used = True
            shot = self._shot()
            if shot.button("return_home"):
                break
            leave = shot.button("end_battle")
            if not leave:
                lost += 1
                if lost >= 8:
                    self.failures += 1
                    self.log("Kampfbildschirm verloren.", "warn")
                    return
                continue
            lost = 0
            now_loot = shot.loot()
            if now_loot and now_loot != last_loot:
                last_loot = now_loot
                changed = self.clock()
            stale = settings["end_stale"] and self.clock() - changed >= settings["end_stale"] \
                and self.clock() - started >= 35
            if stale or self.clock() - started >= MAX_BATTLE:
                self.log("Keine neue Beute mehr, beende den Kampf." if stale else "Zeit um, beende den Kampf.")
                self._end_battle(leave)
                shot, name, _ = self._wait_for(("return_home",), 20)
                if not name:
                    self.failures += 1
                    return
                break
        self._finish(loot, last_loot)

    def _finish(self, first, last) -> None:
        self.status = "Kampf beendet…"
        self._wait(2.5)  # Ergebnis zaehlt noch hoch
        shot = self._shot()
        values = [v for v, _ in shot.numbers(layout.REGIONS["result_loot"]) if v < 10_000_000]
        if len(values) >= 2:
            gold, elixir = values[0], values[1]
            dark = values[2] if len(values) > 2 and values[2] < 100_000 else 0
        else:  # Ersatz: was vom Gegner verschwunden ist
            gold, elixir, dark = (max(0, a - b) for a, b in zip(first, last))
        self.stats.add(gold=gold, elixir=elixir, dark=dark, attacks=1)
        self.failures = 0
        self.log(f"Beute: {notify.short(gold)} Gold, {notify.short(elixir)} Elixier", "good")
        if self.stats.session["attacks"] % 10 == 0:
            self._report("RaidPilot Zwischenstand")
        point = shot.button("return_home")
        if point:
            self._tap(point, 3)

    # ---------- Bauarbeiterbasis (Beta) ----------
    def _attack_builder(self, settings) -> None:
        self.status = "Öffne Angriff…"
        point = self._shot().button("attack_home")
        if not point:
            return
        self._tap(point, 1.2)
        shot, name, point = self._wait_for(("find_match", "army_attack"), 12)
        if name:
            self._tap(point, 2)
        shot, name, _ = self._wait_for(("end_battle",), 60)
        if not name:
            self.failures += 1
            self.log("Kein Kampf gestartet.", "warn")
            return
        started = self.clock()
        sides = army.choose_sides(settings["style"], "all", self.rng)
        side_map = layout.sides()
        deployed_at = None
        while self.clock() - started < 420:
            shot = self._shot()
            if shot.button("return_home"):
                self._wait(2)
                self.stats.add(attacks=1)
                self.failures = 0
                self.log("Kampf auf der Bauarbeiterbasis beendet.", "good")
                done = self._shot().button("return_home")
                if done:
                    self._tap(done, 3)
                return
            if deployed_at is None or self.clock() - deployed_at >= 20:
                # Erneut absetzen deckt auch die zweite Stufe ab; Heldentippen loest Faehigkeiten aus
                self.status = "Setze Truppen ab…"
                slots = army.detect_slots(shot)
                positions = [(s.x, s.y) for s in slots if s.role != "skip"] or \
                            [shot.px((0.12 + i * 0.075, 0.91)) for i in range(8)]
                targets = army.line_points(side_map, sides, len(positions))
                for position, target in zip(positions, targets):
                    self._tap(position, 0.2)
                    self._tap(shot.px(target), 0.2)
                deployed_at = self.clock()
            self.status = "Kampf läuft…"
            self._wait(3)
        self.failures += 1

    # ---------- Mauern (Beta) ----------
    def _upgrade_walls(self, settings, limit: int = 5) -> None:
        for _ in range(limit):
            shot = self._go_home()
            before = shot.storage()
            if not before or max(before) < settings["max_storage"] * 0.75:
                return
            self.status = "Verbessere Mauern…"
            self._tap(shot.px(layout.POINTS["builder_menu"]), 1.2)
            entry = None
            for _scroll in range(6):
                shot = self._shot()
                for word in screen_mod.join_lines(shot.words(layout.REGIONS["builder_list"])):
                    if any(w in screen_mod.normalize(word.text) for w in layout.WALL_WORDS):
                        entry = word
                        break
                if entry:
                    break
                self.adb.swipe(*shot.px((0.5, 0.62)), *shot.px((0.5, 0.30)), 500)
                self._wait(1.0)
            if not entry:
                self.log("Keine Mauer in der Bauliste gefunden.", "warn")
                self._tap(shot.px(layout.POINTS["builder_menu"]), 0.8)
                return
            self._tap(tuple(int(v) for v in entry.center), 1.5)
            shot = self._shot()
            button = shot.button("upgrade")
            if not button:
                self.log("Knopf zum Verbessern nicht gefunden.", "warn")
                self.adb.back()
                return
            self._tap(button, 1.3)
            shot = self._shot()
            if shot.shows_gems():
                self.adb.back()
                self.log("Nicht genug Ressourcen für die nächste Mauer (Juwelen werden nie ausgegeben).")
                return
            confirm = shot.button("confirm")
            if not confirm:
                self.adb.back()
                return
            self._tap(confirm, 2)
            shot = self._shot()
            if shot.shows_gems():
                self.adb.back()
                return
            after = self._go_home().storage()
            if not after or sum(after) >= sum(before):
                self.log("Mauer-Upgrade nicht bestätigt.", "warn")
                return
            self.stats.add(walls=1)
            self.log("Mauer verbessert.", "good")

    # ---------- Spenden (Beta) ----------
    def _donate(self) -> None:
        self.status = "Spende Truppen…"
        shot = self._shot()
        self._tap(shot.px(layout.POINTS["chat_open"]), 1.2)
        shot = self._shot()
        button = shot.button("donate")
        if button:
            self._tap(button, 1.2)
            shot = self._shot()
            if shot.contains_word(layout.PURCHASE_WORDS, layout.REGIONS["donate_popup"]):
                self.log("Spendenfenster erwähnt Juwelen, überspringe.", "warn")
            else:
                region = layout.REGIONS["donate_popup"]
                cards = [w for w in shot.words(region) if army.COUNT_RE.match(w.text.strip())][:3]
                for word in cards:
                    x, y = word.center
                    self._tap((int(x), int(y + shot.height * 0.05)), 0.4)
                if cards:
                    self.log("Truppen gespendet.")
            self.adb.back()
            self._wait(0.8)
        shot = self._shot()
        if not shot.button("attack_home") or shot.button("donate"):
            self._tap(shot.px(layout.POINTS["chat_close"]), 0.8)
