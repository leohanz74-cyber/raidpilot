"""Control of MuMu Player instances through its own command line tool."""
import json
import os
import subprocess
import sys
from pathlib import Path

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
TOOLS = ("MuMuManager.exe", "mumu-cli.exe")


class MumuError(Exception):
    pass


def find_manager():
    """Path of MuMuManager.exe / mumu-cli.exe or None."""
    roots = [os.environ.get(v) for v in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")]
    roots = [Path(r) for r in roots if r]
    if sys.platform == "win32":
        roots += [Path(f"{d}:/Program Files") for d in "CDEF"]
    for root in roots:
        for product in ("MuMuPlayer", "MuMuPlayerGlobal-12.0", "MuMuPlayer-12.0", "MuMu Player 12"):
            for sub in ("nx_main", "shell"):
                for tool in TOOLS:
                    path = root / "Netease" / product / sub / tool
                    if path.is_file():
                        return path
    return None


class Mumu:
    def __init__(self, manager=None, index: int = 0):
        self.manager = manager or find_manager()
        self.index = index

    @property
    def available(self) -> bool:
        return self.manager is not None

    def _run(self, *args, timeout: float = 40) -> str:
        if not self.manager:
            raise MumuError("MuMu Player was not found.")
        try:
            proc = subprocess.run([str(self.manager), *args], capture_output=True, timeout=timeout,
                                  creationflags=_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MumuError(f"MuMu did not answer: {exc}") from exc
        return proc.stdout.decode("utf-8", "replace")

    @staticmethod
    def parse_info(output: str) -> dict:
        start, end = output.find("{"), output.rfind("}")
        if start < 0 or end < start:
            raise MumuError("MuMu returned no instance information.")
        try:
            return json.loads(output[start:end + 1])
        except ValueError as exc:
            raise MumuError("MuMu returned unreadable instance information.") from exc

    def info(self) -> dict:
        return self.parse_info(self._run("info", "-v", str(self.index)))

    def launch(self) -> None:
        self._run("control", "-v", str(self.index), "launch")

    @staticmethod
    def serial_of(info: dict):
        """'127.0.0.1:16384' once Android is running, else None."""
        if not info.get("is_android_started") or not info.get("adb_port"):
            return None
        return f"{info.get('adb_host_ip') or '127.0.0.1'}:{info['adb_port']}"
