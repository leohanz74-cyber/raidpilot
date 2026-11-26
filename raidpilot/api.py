"""Bridge between the window (JavaScript) and Python."""
import base64
import functools
import os
import subprocess
import sys
import threading

import cv2

from . import notify, settings, store, templates, updater
from .adb import Adb, AdbError
from .bot import Bot
from .logbook import Log
from .mumu import Mumu, MumuError
from .ocr import Ocr
from .stats import Stats
from .version import VERSION

SIZE = (440, 760)
PROFILE = "profile.json"
UPDATES = "update.json"


def api_call(func):
    @functools.wraps(func)
    def wrapper(self, *args):
        try:
            result = func(self, *args) or {}
            return {"ok": True, **result}
        except (AdbError, MumuError, updater.UpdateError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # never leave the window hanging
            self._log(f"Error in {func.__name__}: {exc}", "error")
            return {"ok": False, "error": f"Unexpected error: {exc}"}

    return wrapper


class Api:
    # All attributes start with _ so pywebview does not mirror them to JavaScript
    def __init__(self, adb=None, ocr=None, emulator="auto", check_updates: bool = True):
        self._log = Log()
        self._lock = threading.Lock()
        self._adb = adb or Adb()
        self._ocr = ocr or Ocr()
        self._mumu = Mumu() if emulator == "auto" else emulator
        self._bot = None
        self._stats = Stats()
        self._frame = None
        self._window = None
        self._update = None
        self._auto = False          # install the update found at the start without asking
        self._installing = False
        self._log(f"RaidPilot {VERSION} started.")
        threading.Thread(target=self._warm_up, daemon=True).start()
        if check_updates:
            threading.Thread(target=self._look_for_update, daemon=True).start()

    def _attach(self, window) -> None:
        self._window = window

    def _running(self) -> bool:
        return bool(self._bot and self._bot.running)

    def _shutdown(self) -> None:
        if self._running():
            self._bot.stop()
            self._bot.join(5)

    def _warm_up(self) -> None:
        try:
            self._ocr.warm()
        except Exception as exc:  # shown again with details when the bot starts
            self._log(f"Text recognition could not be loaded: {exc}", "warn")

    def _capture(self, name: str, image) -> None:
        """Keeps the latest pictures of an attack to look into problems."""
        folder = store.data_dir() / "captures"
        folder.mkdir(exist_ok=True)
        ok, data = cv2.imencode(".png", image)
        if ok:
            (folder / f"{name}.png").write_bytes(data.tobytes())

    def _find_update(self):
        """Version number of a newer release, or None."""
        self._update = updater.check()
        if not self._update:
            return None
        self._log(f"Update {self._update['version']} is available.", "good")
        return self._update["version"]

    def _look_for_update(self) -> None:
        """Runs once at the start. Only this finding is installed on its own, and each version only
        once: an update that does not take must not restart the program again and again."""
        try:
            version = self._find_update()
        except updater.UpdateError as exc:
            self._log(f"Update check failed: {exc}", "warn")
            return
        self._auto = bool(version) and store.load(UPDATES, {}).get("tried") != version

    def _player(self) -> str:
        return store.load(PROFILE, {}).get("player", "")

    def _save_player(self, name: str) -> None:
        store.save(PROFILE, {"player": name})

    # ---------- start ----------
    @api_call
    def boot(self):
        return {"version": VERSION, "settings": settings.load(), "choices": settings.choices(),
                "unavailable": settings.UNAVAILABLE, "event_troops": len(templates.index())}

    @api_call
    def save_setting(self, key, value):
        with self._lock:
            return {"settings": settings.update(key, value)}

    # ---------- devices ----------
    def _mumu_serial(self):
        """(ADB address of the running MuMu instance #0 or None, MuMu installed?)"""
        if not (self._mumu and self._mumu.available):
            return None, False
        try:
            return self._mumu.serial_of(self._mumu.info()), True
        except MumuError as exc:
            self._log(str(exc), "warn")
            return None, True

    @api_call
    def devices(self):
        serial, installed = self._mumu_serial()
        if serial:
            try:
                self._adb.connect(serial)
            except AdbError:
                pass
        found = self._adb.devices()
        online = [d["serial"] for d in found if d["state"] == "device"]
        selected = settings.load()["device"]
        if selected:
            good = selected in online
            status = "Connected" if good else "Offline"
        elif installed:
            good = bool(serial)
            status = f"MuMu Player #0 is running ({serial})" if serial else \
                "MuMu Player #0 is off. START launches it automatically."
        else:
            good = bool(online)
            status = f"Using {online[0]}" if online else "No device online. Start your emulator."
        if selected and selected not in [d["serial"] for d in found]:
            found.append({"serial": selected, "state": "offline"})
        return {"devices": found, "selected": selected, "status": status, "good": good, "mumu": installed}

    @api_call
    def restart_adb(self):
        if self._running():
            raise ValueError("Stop the bot first.")
        self._log("Restarting the ADB server…")
        self._adb.restart_server()
        self._log("ADB server restarted.", "good")
        return self.devices()

    # ---------- event troop ----------
    def _grab(self):
        if self._running() and self._adb.serial:
            return self._adb.screenshot()
        serial = settings.load()["device"] or self._mumu_serial()[0]
        if serial:
            try:
                self._adb.connect(serial)
            except AdbError:
                pass
        online = [d["serial"] for d in self._adb.devices() if d["state"] == "device"]
        if serial not in online:
            serial = online[0] if online and not serial else None
        if not serial:
            raise ValueError("The emulator is not running. Start it and open your army first.")
        self._adb.serial = serial
        return self._adb.screenshot()

    @api_call
    def capture_event(self):
        self._frame = self._grab()
        ok, data = cv2.imencode(".jpg", self._frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError("The screenshot could not be converted.")
        return {"image": "data:image/jpeg;base64," + base64.b64encode(data.tobytes()).decode()}

    @api_call
    def save_event_troop(self, x, y):
        if self._frame is None:
            raise ValueError("Capture the screen first.")
        templates.add(self._frame, x, y)
        self._log("Event troop icon saved.", "good")
        return {"event_troops": len(templates.index())}

    @api_call
    def clear_event_troops(self):
        templates.clear()
        self._log("Saved event troop icons removed.")
        return {"event_troops": 0}

    # ---------- Discord ----------
    @api_call
    def connect_discord(self, url):
        url = str(url).strip()
        if not url:
            raise ValueError("Paste your webhook address first.")
        settings.validate("webhook", url)
        if not notify.send(url, "RaidPilot is connected.", self._log, wait=True):
            raise ValueError("Discord did not accept the message. Check the address.")
        return self.save_setting("webhook", url)

    @api_call
    def disconnect_discord(self):
        return self.save_setting("webhook", "")

    # ---------- bot ----------
    @api_call
    def start(self):
        with self._lock:
            if self._installing:
                raise ValueError("An update is being installed, one moment.")
            if self._running():
                return
            self._auto = False  # from now on only a click installs an update
            self._bot = Bot(self._adb, self._ocr, settings.load, self._stats, self._log,
                            emulator=self._mumu, on_player=self._save_player, on_capture=self._capture)
            self._log("Bot started.", "good")
            self._bot.start()

    @api_call
    def stop(self):
        if self._bot:
            self._bot.stop()

    @api_call
    def poll(self, last_id=0, generation=0):
        if generation != self._log.generation:
            last_id = 0
        bot = self._bot
        return {
            "running": self._running(),
            "status": bot.status if bot else "Ready",
            "error": bot.last_error if bot else "",
            "session": self._stats.snapshot(),
            "lifetime": self._stats.lifetime(),
            "player": self._player(),
            "log": self._log.since(int(last_id)),
            "generation": self._log.generation,
            "update": self._update["version"] if self._update else None,
            "auto_update": self._auto and not self._running(),
        }

    @api_call
    def clear_log(self):
        self._log.clear()

    # ---------- updates and window ----------
    @api_call
    def check_update(self):
        version = self._find_update()
        if not version:
            self._log(f"RaidPilot {VERSION} is up to date.")
        return {"update": version}

    @api_call
    def install_update(self, auto=False):
        """auto: started by the window itself right after the start; never stops a running bot."""
        with self._lock:
            update = self._update
            if auto and (not self._auto or self._running()):
                return {"result": None}
            if not update or self._installing:
                raise ValueError("There is no update.")
            self._auto = False
            self._installing = True
        try:
            self._shutdown()
            self._log(f"Installing update {update['version']}…")
            result = updater.install(
                update, downloaded=lambda: store.save(UPDATES, {"tried": update["version"]}) if auto else None)
        except Exception as exc:
            self._installing = False
            self._log(f"The update was not installed: {exc}", "warn")
            raise
        self._update = None
        threading.Timer(1.5, self._restart, args=(result == "restart",)).start()
        return {"result": result}

    def _restart(self, relaunch: bool) -> None:
        if relaunch:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            launcher = os.path.join(root, "START.bat")
            if sys.platform == "win32" and os.path.exists(launcher):
                # START.bat installs new requirements if needed
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
