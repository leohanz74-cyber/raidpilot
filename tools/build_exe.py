"""Builds dist/RaidPilot/RaidPilot.exe (Windows, needs pyinstaller). Used by the release workflow."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    import PyInstaller.__main__

    os.chdir(ROOT)
    separator = os.pathsep
    PyInstaller.__main__.run([
        "--noconfirm", "--clean", "--windowed", "--name", "RaidPilot", "--icon", "raidpilot/ui/icon.ico",
        "--add-data", f"raidpilot/ui{separator}raidpilot/ui",
        "--add-data", f"raidpilot/storages.onnx{separator}raidpilot",
        "--collect-all", "rapidocr", "--collect-all", "webview", "main.py",
    ])


if __name__ == "__main__":
    sys.exit(main())
