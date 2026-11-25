"""Bruecke zwischen Oberflaeche (JavaScript) und Python."""
import base64
import functools
import json
import os
import subprocess
import sys
import threading
import time

import cv2

from . import accounts, army, layout, notify, settings, store, templates, updater
from .adb import Adb, AdbError
from .bot import Bot
from .logbook import Log
from .ocr import Ocr
from .screen import Screen
from .stats import Stats
from .version import VERSION

SIZES = {"normal": (420, 700), "wide": (1060, 700)}


def api_call(func):
    @functools.wraps(func)
    def wrapper(self, *args):
        try:
            result = func(self, *args) or {}
            return {"ok": True, **result}
        except (accounts.AccountError, AdbError, updater.UpdateError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # nie die Oberflaeche haengen lassen
            self._log(f"Fehler in {func.__name__}: {exc}", "error")
            return {"ok": False, "error": f"Unerwarteter Fehler: {exc}"}

    return wrapper


class Api:
    # Alle Attribute beginnen mit _, damit pywebview sie nicht nach JavaScript spiegelt
    def __init__(self, adb=None, ocr=None, check_updates: bool = True):
        self._log = Log()
        self._settings_lock = threading.Lock()
        config = settings.load()
        self._adb = adb or Adb(config["adb_path"])
        if config["device"] and not self._adb.serial:
            self._adb.serial = config["device"]
        self._ocr = ocr or Ocr()
        self._user = None
        self._bot = None
        self._stats = Stats()
        self._frame = None
        self._window = None
        self._update = None
        self._log(f"RaidPilot {VERSION} gestartet.")
        if check_updates:
            threading.Thread(target=self._look_for_update, daemon=True).start()

    def _attach(self, window) -> None:
        self._window = window

    def _shutdown(self) -> None:
        if self._bot and self._bot.running:
            self._bot.stop()
            self._bot.join(5)

    def _look_for_update(self) -> None:
        try:
            self._update = updater.check()
            if self._update:
                self._log(f"Update {self._update['version']} verfügbar.", "good")
        except updater.UpdateError:
            pass

    def _require_user(self) -> None:
        if not self._user:
            raise ValueError("Bitte zuerst anmelden.")

    def _signed_in(self, name: str) -> dict:
        self._user = name
        if not (self._bot and self._bot.running):
            self._stats = Stats(name)
        return {"user": name}

    # ---------- Start & Profil ----------
    @api_call
    def boot(self):
        name = accounts.auto_sign_in()
        if name:
            self._signed_in(name)
        return {"version": VERSION, "user": self._user, "has_users": accounts.has_users(),
                "settings": settings.load(), "choices": settings.choices(),
                "buttons": layout.BUTTON_TITLES}

    @api_call
    def sign_in(self, name, password, remember=True):
        return self._signed_in(accounts.sign_in(name, password, remember))

    @api_call
    def sign_up(self, name, password, remember=True):
        return self._signed_in(accounts.sign_up(name, password, remember))

    @api_call
    def sign_out(self):
        self._shutdown()
        accounts.sign_out()
        self._user = None

    @api_call
    def account(self):
        self._require_user()
        return {"name": self._user, "created": accounts.created_at(self._user), "lifetime": self._stats.lifetime()}

    # ---------- Einstellungen & Geraete ----------
    @api_call
    def save_setting(self, key, value):
        with self._settings_lock:
            current = settings.update(key, value)
        if key == "adb_path":
            self._adb.configured = current["adb_path"]
        if key == "device" and not (self._bot and self._bot.running):
            self._adb.serial = current["device"]
        return {"settings": current}

    @api_call
    def devices(self):
        found = self._adb.devices()
        online = [d["serial"] for d in found if d["state"] == "device"]
        busy = self._bot and self._bot.running
        if not busy and online and self._adb.serial not in online:
            self._adb.serial = online[0]
            settings.update("device", online[0])
        self._log(f"{len(online)} Gerät(e) online." if online else "Kein Gerät online. Läuft der Emulator?",
                  "info" if online else "warn")
        return {"devices": found, "selected": self._adb.serial, "adb": self._adb.path}

    @api_call
    def restart_adb(self):
        self._log("Starte ADB-Server neu…")
        self._adb.restart_server()
        return self.devices()

    @api_call
    def pick_adb(self):
        if not self._window:
            raise ValueError("Nur im Programmfenster möglich.")
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("adb (*.exe)",))
        if not chosen:
            return {"settings": settings.load()}
        return self.save_setting("adb_path", chosen[0])

    @api_call
    def test_webhook(self):
        url = settings.load()["webhook"]
        if not url:
            raise ValueError("Trage zuerst eine Webhook-Adresse ein.")
        if not notify.send(url, "RaidPilot ist verbunden.", self._log, wait=True):
            raise ValueError("Discord hat die Meldung nicht angenommen.")

    # ---------- Bot ----------
    @api_call
    def start(self):
        self._require_user()
        if self._bot and self._bot.running:
            return
        config = settings.load()
        self._adb.configured = config["adb_path"]
        self._adb.serial = config["device"] or self._adb.serial
        if self._adb.serial:
            online = [d["serial"] for d in self._adb.devices() if d["state"] == "device"]
            if self._adb.serial not in online:
                self._adb.serial = ""  # gespeichertes Geraet ist weg: neu waehlen lassen
        self._bot = Bot(self._adb, self._ocr, settings.load, self._stats, self._log)
        self._bot.start()
        self._log("Bot gestartet.", "good")

    @api_call
    def stop(self):
        if self._bot:
            self._bot.stop()

    @api_call
    def poll(self, last_id=0, generation=0):
        if generation != self._log.generation:
            last_id = 0
        bot = self._bot
        running = bool(bot and bot.running)
        return {
            "running": running,
            "status": bot.status if bot else "Bereit",
            "error": bot.last_error if bot else "",
            "session": self._stats.snapshot(),
            "log": self._log.since(int(last_id)),
            "generation": self._log.generation,
            "update": self._update["version"] if self._update else None,
        }

    @api_call
    def clear_log(self):
        self._log.clear()

    # ---------- Einrichtung ----------
    def _need_frame(self):
        if self._frame is None:
            raise ValueError("Nimm zuerst ein Bild auf.")
        return self._frame

    def _frame_payload(self) -> dict:
        ok, data = cv2.imencode(".jpg", self._frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError("Bild konnte nicht umgewandelt werden.")
        height, width = self._frame.shape[:2]
        return {"image": "data:image/jpeg;base64," + base64.b64encode(data.tobytes()).decode(),
                "width": width, "height": height}

    @api_call
    def capture(self):
        if not self._adb.serial:
            result = self.devices()
            if not result.get("ok") or not self._adb.serial:
                raise ValueError("Kein Gerät online. Starte zuerst den Emulator.")
        self._frame = self._adb.screenshot()
        return self._frame_payload()

    @api_call
    def analyze(self):
        shot = Screen(self._need_frame(), self._ocr)
        found = []
        for name, title in layout.BUTTON_TITLES.items():
            point = shot.button(name)
            if point:
                found.append({"name": name, "title": title, "x": point[0] / shot.width, "y": point[1] / shot.height})
        slots = army.detect_slots(shot)
        if slots:
            army.assign_roles(shot, slots, settings.load())
        return {
            "buttons": found,
            "loot": shot.loot(),
            "storage": shot.storage(),
            "slots": [{"x": s.x / shot.width, "y": s.y / shot.height, "count": s.count, "role": s.role} for s in slots],
        }

    @api_call
    def layout_info(self):
        return {"sides": layout.sides(), "templates": templates.index()}

    @api_call
    def add_template(self, kind, name, rect):
        templates.add(kind, name, self._need_frame(), rect)
        self._log(f"Vorlage „{name}“ gespeichert.", "good")
        return {"templates": templates.index()}

    @api_call
    def delete_template(self, filename):
        templates.remove(filename)
        return {"templates": templates.index()}

    @api_call
    def set_side(self, key, start, end):
        layout.set_side(key, start, end)
        return {"sides": layout.sides()}

    @api_call
    def reset_sides(self):
        layout.reset_sides()
        return {"sides": layout.sides()}

    @api_call
    def save_diagnostics(self):
        frame = self._need_frame()
        folder = store.data_dir() / "diagnose" / time.strftime("%Y%m%d-%H%M%S")
        folder.mkdir(parents=True, exist_ok=True)
        ok, data = cv2.imencode(".png", frame)
        (folder / "bild.png").write_bytes(data.tobytes())
        words = Screen(frame, self._ocr).words()
        report = {"version": VERSION, "size": [frame.shape[1], frame.shape[0]],
                  "words": [[w.text, round(w.x), round(w.y), round(w.w), round(w.h)] for w in words]}
        (folder / "texte.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        self._open(folder)
        return {"folder": str(folder)}

    def _open(self, path) -> None:
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            self._log(f"Ordner: {path}")

    @api_call
    def open_data_folder(self):
        self._open(store.data_dir())

    # ---------- Updates & Fenster ----------
    @api_call
    def check_update(self):
        self._update = updater.check()
        return {"update": self._update["version"] if self._update else None}

    @api_call
    def install_update(self):
        if not self._update:
            raise ValueError("Kein Update vorhanden.")
        self._shutdown()
        result = updater.install(self._update)
        self._update = None
        threading.Timer(1.5, self._restart, args=(result == "restart",)).start()
        return {"result": result}

    def _restart(self, relaunch: bool) -> None:
        if relaunch:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            launcher = os.path.join(root, "START.bat")
            if sys.platform == "win32" and os.path.exists(launcher):
                # START.bat installiert bei Bedarf neue Abhaengigkeiten
                subprocess.Popen(["cmd", "/c", "start", "", launcher], cwd=root)
        if self._window:
            self._window.destroy()

    @api_call
    def minimize(self):
        if self._window:
            self._window.minimize()

    @api_call
    def close(self):
        self._shutdown()
        if self._window:
            self._window.destroy()

    @api_call
    def set_size(self, mode):
        if self._window and mode in SIZES:
            self._window.resize(*SIZES[mode])
