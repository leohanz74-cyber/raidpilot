"""Kleiner ADB-Client. Er liest nur Bildschirmfotos und sendet Tipp-Befehle - kein Eingriff ins Spiel."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

PACKAGE = "com.supercell.clashofclans"
# Uebliche lokale Ports: MuMu 12, MuMu alt, LDPlayer/BlueStacks, Nox
PORTS = (16384, 16416, 16448, 7555, 5555, 5557, 5565, 62001)
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class AdbError(Exception):
    pass


def _candidates():
    program_dirs = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    program_dirs = [Path(p) for p in program_dirs if p]
    drives = [Path(f"{d}:/") for d in "CDEF"] if sys.platform == "win32" else []
    exe = "adb.exe" if sys.platform == "win32" else "adb"

    for base in program_dirs + [d / "Program Files" for d in drives]:
        for mumu in ("MuMuPlayer", "MuMuPlayerGlobal-12.0", "MuMuPlayer-12.0", "MuMu Player 12"):
            for sub in ("nx_main", "shell", "nx_device/12.0/shell"):
                yield base / "Netease" / mumu / sub / exe
        yield base / "BlueStacks_nxt" / "HD-Adb.exe"
        yield base / "Nox" / "bin" / exe
    for drive in drives:
        for ld in ("LDPlayer/LDPlayer9", "LDPlayer/LDPlayer4.0", "LDPlayer9"):
            yield drive / ld / exe
    local = os.environ.get("LOCALAPPDATA")
    if local:
        yield Path(local) / "Android" / "Sdk" / "platform-tools" / exe
    yield Path(__file__).resolve().parent.parent / "platform-tools" / exe


def find_adb(configured: str = "") -> str:
    if configured and Path(configured).is_file():
        return configured
    for path in _candidates():
        if path.is_file():
            return str(path)
    found = shutil.which("adb")
    if found:
        return found
    raise AdbError("adb wurde nicht gefunden. Starte deinen Emulator einmal oder wähle adb.exe in den Einstellungen.")


class Adb:
    def __init__(self, path: str = ""):
        self.configured = path
        self.serial = ""

    @property
    def path(self) -> str:
        return find_adb(self.configured)

    def _run(self, args, timeout: float = 20, device: bool = True) -> bytes:
        command = [self.path]
        if device:
            if not self.serial:
                raise AdbError("Kein Gerät ausgewählt.")
            command += ["-s", self.serial]
        command += list(args)
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb antwortet nicht ({args[0]}).") from exc
        except OSError as exc:
            raise AdbError(f"adb konnte nicht gestartet werden: {exc}") from exc
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
            raise AdbError(message or f"adb Fehler {proc.returncode}")
        return proc.stdout

    @staticmethod
    def parse_devices(output: str) -> list:
        devices = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devices.append({"serial": parts[0], "state": parts[1]})
        return devices

    def devices(self, connect: bool = True) -> list:
        if connect:
            for port in PORTS:
                try:
                    self._run(["connect", f"127.0.0.1:{port}"], timeout=4, device=False)
                except AdbError:
                    pass
        found = self.parse_devices(self._run(["devices"], device=False).decode("utf-8", "replace"))
        # Geraete, die wirklich online sind, zuerst
        return sorted(found, key=lambda d: (d["state"] != "device", d["serial"]))

    def restart_server(self) -> None:
        try:
            self._run(["kill-server"], device=False)
        except AdbError:
            pass
        self._run(["start-server"], timeout=30, device=False)

    def screenshot(self) -> np.ndarray:
        raw = self._run(["exec-out", "screencap", "-p"], timeout=25)
        # Manche Emulatoren schreiben eine Warnung vor die PNG-Daten
        start = raw.find(b"\x89PNG")
        raw = raw[start:] if start > 0 else raw
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
        if image is None:
            raise AdbError("Bildschirmfoto fehlgeschlagen. Läuft der Emulator?")
        return image

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(int(x)), str(int(y))])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> None:
        self._run(["shell", "input", "swipe", *(str(int(v)) for v in (x1, y1, x2, y2, ms))], timeout=20 + ms / 1000)

    def back(self) -> None:
        self._run(["shell", "input", "keyevent", "4"])

    def launch_game(self) -> None:
        self._run(["shell", "monkey", "-p", PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"])

    def stop_game(self) -> None:
        self._run(["shell", "am", "force-stop", PACKAGE])
