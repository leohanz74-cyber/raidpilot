"""Small ADB client. It only reads screenshots and sends touch input; the game itself is never modified."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from . import zoom

PACKAGE = "com.supercell.clashofclans"
# Common local ports: MuMu 12, old MuMu, LDPlayer/BlueStacks, Nox
PORTS = (16384, 16416, 16448, 7555, 5555, 5557, 5565, 62001)
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class AdbError(Exception):
    pass


def _candidates():
    program_dirs = [os.environ.get(v) for v in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")]
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
    raise AdbError("adb was not found. Install MuMu Player or another Android emulator.")


class Adb:
    def __init__(self, path: str = ""):
        self.configured = path
        self.serial = ""
        self._touch = {}

    @property
    def path(self) -> str:
        return find_adb(self.configured)

    def _run(self, args, timeout: float = 20, device: bool = True) -> bytes:
        command = [self.path]
        if device:
            if not self.serial:
                raise AdbError("No device selected.")
            command += ["-s", self.serial]
        command += list(args)
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb does not respond ({args[0]}).") from exc
        except OSError as exc:
            raise AdbError(f"adb could not be started: {exc}") from exc
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
            raise AdbError(message or f"adb error {proc.returncode}")
        return proc.stdout

    @staticmethod
    def parse_devices(output: str) -> list:
        devices = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devices.append({"serial": parts[0], "state": parts[1]})
        return devices

    def connect(self, serial: str) -> None:
        if ":" in serial:
            self._run(["connect", serial], timeout=10, device=False)

    def devices(self, connect: bool = True) -> list:
        if connect:
            for port in PORTS:
                try:
                    self._run(["connect", f"127.0.0.1:{port}"], timeout=4, device=False)
                except AdbError:
                    pass
        found = self.parse_devices(self._run(["devices"], device=False).decode("utf-8", "replace"))
        # Devices that are really online first
        return sorted(found, key=lambda d: (d["state"] != "device", d["serial"]))

    def restart_server(self) -> None:
        try:
            self._run(["kill-server"], device=False)
        except AdbError:
            pass
        self._run(["start-server"], timeout=30, device=False)

    def shell(self, command: str, timeout: float = 30) -> str:
        return self._run(["shell", command], timeout=timeout).decode("utf-8", "replace")

    def screenshot(self) -> np.ndarray:
        raw = self._run(["exec-out", "screencap", "-p"], timeout=25)
        # Some emulators print a warning in front of the PNG data
        start = raw.find(b"\x89PNG")
        raw = raw[start:] if start > 0 else raw
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
        if image is None:
            raise AdbError("Screenshot failed. Is the emulator running?")
        return image

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def tap_many(self, points) -> None:
        """Several taps with one adb call."""
        if points:
            self.shell(";".join(f"input tap {int(x)} {int(y)}" for x, y in points), timeout=20 + len(points))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> None:
        self.shell("input swipe " + " ".join(str(int(v)) for v in (x1, y1, x2, y2, ms)), timeout=20 + ms / 1000)

    def back(self) -> None:
        self.shell("input keyevent 4")

    def zoom_out(self, size) -> bool:
        """Two-finger pinch. False if the emulator offers no multi-touch input."""
        if self.serial not in self._touch:
            devices = zoom.parse_touch_devices(self.shell("getevent -pl"))
            self._touch[self.serial] = devices[0] if devices else None
        device = self._touch[self.serial]
        if device is None:
            return False
        events = zoom.gesture_events(device, zoom.pinch_paths(size, zoom_out=True), size)
        output = self.shell(zoom.shell_script(device, events), timeout=60)
        return "denied" not in output.lower() and "not found" not in output.lower()

    def launch_game(self) -> None:
        self.shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")

    def stop_game(self) -> None:
        self.shell(f"am force-stop {PACKAGE}")
