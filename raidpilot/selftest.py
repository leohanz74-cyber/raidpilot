"""Checks that a built program is complete and starts: RaidPilot.exe --self-test <report file>.
It uses an empty data folder and does not look for updates."""
import os
import tempfile
import threading
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

from .version import VERSION

WINDOW_TIMEOUT = 90


def check_recognition() -> None:
    from . import ocr, storages

    picture = np.full((120, 520, 3), (40, 40, 40), np.uint8)
    cv2.putText(picture, "End Battle", (40, 80), cv2.FONT_HERSHEY_DUPLEX, 1.8, (255, 255, 255), 3, cv2.LINE_AA)
    text = "".join(word.text for word in ocr.Ocr().read(picture)).lower().replace(" ", "")
    if "endbattle" not in text:
        raise RuntimeError(f"Text recognition read {text!r}.")
    storages.Finder().find(np.full((900, 1600, 3), (62, 104, 74), np.uint8))


def check_window() -> None:
    """Opens the real window and waits until the page has talked to the program."""
    import webview

    from .api import SIZE, Api
    from .app import ui_path

    api = Api(emulator=None, check_updates=False)
    window = webview.create_window("RaidPilot self-test", url=ui_path(), js_api=api,
                                   width=SIZE[0], height=SIZE[1], frameless=True)
    seen = []

    def probe():
        end = time.monotonic() + WINDOW_TIMEOUT
        while time.monotonic() < end and not seen:
            try:
                if window.evaluate_js("document.querySelector('#version').textContent") == VERSION:
                    seen.append(True)
            except Exception:  # the page is not there yet
                pass
            time.sleep(0.5)
        window.destroy()

    webview.start(probe)
    if not seen:
        raise RuntimeError("The window did not show the program.")


def run(report: Path, window: bool = True) -> int:
    previous = os.environ.get("RAIDPILOT_HOME")
    os.environ["RAIDPILOT_HOME"] = tempfile.mkdtemp(prefix="raidpilot-test-")
    watchdog = threading.Timer(WINDOW_TIMEOUT + 60, os._exit, (3,))
    watchdog.daemon = True
    watchdog.start()
    lines, code = [f"RaidPilot {VERSION}"], 0
    try:
        for name, check in (("recognition", check_recognition), ("window", check_window)):
            if name == "window" and not window:
                continue
            check()
            lines.append(f"{name}: ok")
            report.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        lines.append(traceback.format_exc())
        code = 1
    finally:
        watchdog.cancel()
        if previous is None:
            del os.environ["RAIDPILOT_HOME"]
        else:
            os.environ["RAIDPILOT_HOME"] = previous
    report.write_text("\n".join(lines), encoding="utf-8")
    return code
