"""Program start: open the window."""
import sys
import traceback
from pathlib import Path

from . import power, store
from .api import SIZE, Api


def ui_path() -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return str(base / "raidpilot" / "ui" / "index.html")


def main() -> None:
    try:
        import cv2
        import webview

        power.lower_priority()
        cv2.setNumThreads(2)  # like the text recognition: leave the processor to the emulator

        api = Api()
        width, height = SIZE
        window = webview.create_window(
            "RaidPilot", url=ui_path(), js_api=api, width=width, height=height,
            frameless=True, easy_drag=False, resizable=False, background_color="#0d111f",
        )
        api._attach(window)
        window.events.closing += api._shutdown
        webview.start()
    except Exception:
        report = traceback.format_exc()
        (store.data_dir() / "crash.log").write_text(report, encoding="utf-8")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0, f"RaidPilot could not start.\n\n{report[-900:]}", "RaidPilot", 0x10)
        raise
