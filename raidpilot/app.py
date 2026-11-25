"""Programmstart: Fenster oeffnen."""
import sys
import traceback
from pathlib import Path

from . import store
from .api import SIZES, Api


def ui_path() -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return str(base / "raidpilot" / "ui" / "index.html")


def main() -> None:
    try:
        import webview

        api = Api()
        width, height = SIZES["normal"]
        window = webview.create_window(
            "RaidPilot", url=ui_path(), js_api=api, width=width, height=height,
            frameless=True, easy_drag=False, resizable=False, background_color="#0d111f",
        )
        api._attach(window)
        window.events.closing += api._shutdown
        webview.start()
    except Exception:
        report = traceback.format_exc()
        (store.data_dir() / "absturz.log").write_text(report, encoding="utf-8")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0, f"RaidPilot konnte nicht starten.\n\n{report[-900:]}", "RaidPilot", 0x10)
        raise
