import hashlib
import io
import sys
import zipfile

import cv2
import numpy as np
import pytest

from raidpilot import army, layout, power, selftest, settings, storages, store, templates, updater, zoom
from raidpilot.adb import Adb, decode_raw
from raidpilot.api import Api
from raidpilot.bot import Bot
from raidpilot.mumu import Mumu, MumuError
from raidpilot.screen import Screen, label_matches, parse_number
from raidpilot.version import VERSION

from .fakegame import FakeGame


def test_numbers():
    assert parse_number("1 234 567") == 1_234_567
    assert parse_number("987.654") == 987_654
    assert parse_number("12O 5OO") == 120_500
    assert parse_number("+355000") == 355_000
    assert parse_number("Available Loot:") is None
    assert parse_number("") is None


def test_labels():
    assert label_matches("EndBattle", "End Battle")
    assert label_matches("Find a Matcn", "Find a Match")
    assert not label_matches("Shop", "Attack")
    assert not label_matches("Attack Log", "Next")


def test_settings_are_validated():
    assert settings.load()["heroes"] is False
    assert settings.update("min_loot", 99_000_000)["min_loot"] == 3_000_000
    assert settings.update("max_storage", 99_000_000)["max_storage"] == 31_000_000
    assert settings.update("army", "meteor_golem")["army"] == "meteor_golem"
    for key, value in (("style", "diagonal"), ("mode", "builder"), ("webhook", "https://example.com/x")):
        with pytest.raises(ValueError):
            settings.update(key, value)
    store.save("settings.json", {"schema": settings.SCHEMA, "min_loot": "abc", "army": "thrower"})
    assert settings.load()["min_loot"] == settings.DEFAULTS["min_loot"]
    assert settings.load()["army"] == "thrower"


def test_old_settings_do_not_enable_heroes():
    store.save("settings.json", {"heroes": True, "army": "dragon"})  # file of version 1
    assert settings.load()["heroes"] is False


def test_storage_limit_of_older_versions_is_raised():
    store.save("settings.json", {"schema": 2, "max_storage": 24_000_000, "heroes": True})
    loaded = settings.load()
    assert loaded["max_storage"] == 31_000_000 and loaded["heroes"] is True
    store.save("settings.json", {"schema": 2, "max_storage": 12_000_000})
    assert settings.load()["max_storage"] == 12_000_000
    assert settings.update("max_storage", 24_000_000)["max_storage"] == 24_000_000  # chosen now: kept
    assert settings.load()["max_storage"] == 24_000_000


def test_broken_file_is_kept(home):
    (home / "settings.json").write_text("{broken")
    assert settings.load()["mode"] == "home"
    assert (home / "settings.broken").exists()


def test_device_list():
    out = "List of devices attached\nemulator-5554\toffline\n127.0.0.1:16384\tdevice\n\n"
    assert Adb.parse_devices(out) == [{"serial": "emulator-5554", "state": "offline"},
                                      {"serial": "127.0.0.1:16384", "state": "device"}]


def test_mumu_info():
    info = Mumu.parse_info('noise {"adb_host_ip": "127.0.0.1", "adb_port": 16384, "is_android_started": true}')
    assert Mumu.serial_of(info) == "127.0.0.1:16384"
    assert Mumu.serial_of({"is_android_started": False, "adb_port": 16384}) is None
    with pytest.raises(MumuError):
        Mumu.parse_info("player not found")


GETEVENT = """add device 1: /dev/input/event4
  name:     "Xiaomi Touchscreen"
  events:
    ABS (0003): ABS_MT_SLOT          : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_X    : value 0, min 0, max 900, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y    : value 0, min 0, max 1600, fuzz 0, flat 0, resolution 0
                ABS_MT_PRESSURE      : value 0, min 0, max 100, fuzz 0, flat 0, resolution 0
"""


def test_zoom_gesture_on_portrait_panel():
    device = zoom.parse_touch_devices(GETEVENT)[0]
    assert (device.path, device.max_x, device.max_y, device.slots) == ("/dev/input/event4", 900, 1600, True)
    assert zoom.to_device(device, (0, 0), (1600, 900)) == (900, 0)
    assert zoom.to_device(device, (1599, 899), (1600, 900)) == (0, 1600)
    paths = zoom.pinch_paths((1600, 900), zoom_out=True)
    assert paths[1][0][0] - paths[0][0][0] > paths[1][-1][0] - paths[0][-1][0]
    script = zoom.shell_script(device, zoom.gesture_events(device, paths, (1600, 900)))
    assert script.startswith("sendevent /dev/input/event4 ")


def test_deploy_points_avoid_buttons():
    for name in layout.SIDES:
        for outward in (0, 0.1, 0.25):
            for x, y in army.line_points([name], 30, outward):
                assert 0 < x < 1 and 0 < y <= 0.79 and not layout.blocked(x, y), (name, outward, x, y)
    assert len(army.line_points(["tl", "tr", "br", "bl"], 11)) == 11
    assert len(army.spell_points(["tl"], 5)) == 5


def scouting(ocr):
    game = FakeGame()
    game.state = "scout"
    return Screen(game.render(), ocr)


def test_troop_bar_roles(ocr):
    shot = scouting(ocr)
    slots = army.assign_roles(shot, army.detect_slots(shot))
    assert [(s.role, s.count) for s in slots] == [
        ("troop", 14), ("event", 30), ("siege", 1), ("hero", None), ("hero", None), ("hero", None), ("spell", 5)]
    wardens = [s for s in slots if s.role == "hero" and army.is_warden(shot.image, s.left, s.right)]
    assert [s.index for s in wardens] == [5]
    assert [s.index for s in army.choose_spells(shot.image, slots, "rage")] == [6]
    assert army.choose_spells(shot.image, slots, "none") == []
    assert shot.loot() == (900_000, 120_000, 800)


def _bar(background):
    """A troop bar with four cards over a background of the given brightness."""
    image = np.full((900, 1600, 3), background, np.uint8)
    for left, color in ((121, (230, 170, 90)), (257, (200, 60, 160)), (379, (60, 60, 220)), (512, (220, 90, 200))):
        cv2.rectangle(image, (left, 745), (left + 110, 885), (60, 30, 20), -1)
        cv2.rectangle(image, (left + 3, 748), (left + 107, 882), color, -1)
    return image


@pytest.mark.parametrize("background", [(70, 60, 50), (150, 160, 150)], ids=["dark", "bright"])
def test_cards_are_found_over_dark_and_bright_villages(background):
    image = _bar(background)
    if background[0] > 118:
        image[720:900, :60] = (60, 60, 60)  # the bar gets darker towards the left
    cards = army.find_cards(image)
    assert len(cards) == 4, cards
    for (left, right), expected in zip(cards, (121, 257, 379, 512)):
        assert abs(left - expected) <= 6 and abs(right - expected - 110) <= 6, cards


def test_keep_awake_and_priority():
    on_windows = sys.platform == "win32"
    assert power.keep_awake(True) is on_windows and power.keep_awake(False) is on_windows
    if not on_windows:
        power.lower_priority()  # does nothing elsewhere
        return
    import ctypes

    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.GetPriorityClass.argtypes = [ctypes.c_void_p]
    kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    before = kernel.GetPriorityClass(kernel.GetCurrentProcess())
    try:
        power.lower_priority()
        assert kernel.GetPriorityClass(kernel.GetCurrentProcess()) == 0x4000  # below normal
    finally:
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), before)


def test_captured_event_troop_is_recognised(ocr):
    shot = scouting(ocr)
    image = shot.image.copy()
    # A symbol that only exists on the first card
    cv2.drawMarker(image, (172, 835), (0, 0, 255), cv2.MARKER_STAR, 40, 4)
    templates.add(image, 172 / 1600, 835 / 900)
    marked = Screen(image, ocr)
    assert army.assign_roles(marked, army.detect_slots(marked))[0].role == "event"
    templates.clear()
    assert templates.index() == []


def test_result_and_home(ocr):
    game = FakeGame()
    game.state = "result"
    shot = Screen(game.render(), ocr)
    assert shot.result_loot() == game.total()
    assert shot.button("return_home") and not shot.home()
    game.state = "home"
    shot = Screen(game.render(), ocr)
    assert shot.home() and shot.storage() == (5_000_000, 4_000_000)
    assert shot.player_name() == "TestChief" and shot.builder_button()[0] == 1
    game.state = "welcome"
    assert not Screen(game.render(), ocr).home()


def test_wall_screens(ocr):
    game = FakeGame(storage=(20_000_000, 9_000_000))
    game.state = "panel"
    shot = Screen(game.render(), ocr)
    assert shot.upgrade_panel() and not shot.wall_entries() and not shot.home()
    game.scroll = 5
    shot = Screen(game.render(), ocr)
    assert [price for price, _ in shot.wall_entries()] == [4_800_000, 4_000_000]
    game.wall = 0
    buttons = Screen(game.render(), ocr).upgrade_buttons()
    assert [round(x, -1) for x, _ in buttons] == [400, 570], buttons  # no ring, no "Upgrade More"
    for currency in ("gold", "elixir"):
        game.state, game.currency = "dialog", currency
        shot = Screen(game.render(), ocr)
        point, price, seen = shot.wall_dialog()
        assert (price, seen) == (4_800_000, currency) and not shot.shows_gems()
    game.state = "popup"
    assert Screen(game.render(), ocr).shows_gems()
    game.state = "home"
    assert not Screen(game.render(), ocr).wall_dialog()


def test_window_api(ocr):
    game = FakeGame()
    api = Api(adb=game, ocr=ocr, emulator=None, check_updates=False)
    assert api.boot()["settings"]["heroes"] is False
    assert api.save_setting("walls", True)["settings"]["walls"] is True
    assert not api.save_setting("style", "nope")["ok"]
    devices = api.devices()
    assert devices["ok"] and devices["good"] and devices["selected"] == ""
    game.state = "scout"
    assert api.capture_event()["image"].startswith("data:image/jpeg;base64,")
    assert api.save_event_troop(172 / 1600, 835 / 900)["event_troops"] == 1
    assert api.clear_event_troops()["event_troops"] == 0
    assert not api.connect_discord("https://example.com")["ok"]
    poll = api.poll()
    assert poll["ok"] and not poll["running"] and poll["lifetime"]["attacks"] == 0


def test_update_at_start_installs_itself_once(ocr, monkeypatch):
    installed = []

    def install(info, downloaded=None):
        downloaded()
        installed.append(info["version"])
        return "exit"

    monkeypatch.setattr(updater, "check", lambda: {"version": "9.0.0", "assets": []})
    monkeypatch.setattr(updater, "install", install)
    api = Api(adb=FakeGame(), ocr=ocr, emulator=None, check_updates=False)
    assert api.poll()["auto_update"] is False
    api._look_for_update()
    assert api.poll()["auto_update"] is True
    assert api.install_update(True) == {"ok": True, "result": "exit"} and installed == ["9.0.0"]
    assert api.start()["error"] == "An update is being installed, one moment."
    # If the program starts again and is still old, it offers the button and does not loop
    again = Api(adb=FakeGame(), ocr=ocr, emulator=None, check_updates=False)
    again._look_for_update()
    assert again.poll()["auto_update"] is False and again.poll()["update"] == "9.0.0"
    assert again.install_update(True)["result"] is None and installed == ["9.0.0"]
    assert again.install_update()["result"] == "exit" and installed == ["9.0.0", "9.0.0"]


def test_first_start_after_an_update_says_so(ocr):
    start = lambda: Api(adb=FakeGame(), ocr=ocr, emulator=None, check_updates=False).boot()["updated"]
    assert start() is False and start() is False          # a fresh install says nothing
    store.save("update.json", {"ran": "0.0.1"})
    assert start() is True and start() is False
    store.save("update.json", {"tried": VERSION})         # updated from a version that did not note itself
    assert start() is True and start() is False


def test_update_never_interrupts_a_running_bot(ocr, monkeypatch):
    monkeypatch.setattr(updater, "check", lambda: {"version": "9.0.0", "assets": []})
    monkeypatch.setattr(updater, "install", lambda *a, **k: pytest.fail("must not install"))
    api = Api(adb=FakeGame(), ocr=ocr, emulator=None, check_updates=False)
    api._look_for_update()
    monkeypatch.setattr(api, "_running", lambda: True)
    assert api.poll()["auto_update"] is False and api.install_update(True)["result"] is None
    # Once START was pressed, only a click installs it, also after the bot has stopped
    monkeypatch.setattr(api, "_running", lambda: False)
    monkeypatch.setattr(Bot, "start", lambda self: None)
    api.start()
    assert api.poll()["auto_update"] is False and api.poll()["update"] == "9.0.0"


def test_frozen_update_runs_the_installer(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setattr(updater, "download", lambda asset: b"setup")
    monkeypatch.setattr(updater.subprocess, "Popen", lambda command, **options: calls.append((command, options)))
    info = {"version": "9.0.0", "assets": [{"name": "RaidPilot-9.0.0-Setup.exe", "url": "u"},
                                           {"name": "RaidPilot-source.zip", "url": "u"}]}
    assert updater.install(info, downloaded=lambda: calls.append("downloaded")) == "exit"
    assert calls[0] == "downloaded"
    command, options = calls[1]
    assert command[0].endswith("RaidPilot-9.0.0-Setup.exe") and "/SILENT" in command
    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_failed_update_leaves_the_app_usable(ocr, monkeypatch):
    def install(info, downloaded=None):
        raise updater.UpdateError("Download failed.")

    monkeypatch.setattr(updater, "check", lambda: {"version": "9.0.0", "assets": []})
    monkeypatch.setattr(updater, "install", install)
    api = Api(adb=FakeGame(), ocr=ocr, emulator=None, check_updates=False)
    api._look_for_update()
    assert api.install_update(True) == {"ok": False, "error": "Download failed."}
    assert not api._installing and api.poll()["auto_update"] is False and api.poll()["update"] == "9.0.0"


def test_self_test_of_the_build(tmp_path):
    report = tmp_path / "report.txt"
    assert selftest.run(report, window=False) == 0
    assert report.read_text().splitlines()[1] == "recognition: ok"


def test_check_for_updates_button(ocr, monkeypatch):
    api = Api(adb=FakeGame(), ocr=ocr, emulator=None, check_updates=False)
    monkeypatch.setattr(updater, "check", lambda: None)
    assert api.check_update() == {"ok": True, "update": None} and api.poll()["update"] is None
    monkeypatch.setattr(updater, "check", lambda: {"version": "9.0.0", "assets": []})
    assert api.check_update()["update"] == "9.0.0" and api.poll()["update"] == "9.0.0"

    def offline():
        raise updater.UpdateError("No connection to GitHub.")

    monkeypatch.setattr(updater, "check", offline)
    assert api.check_update() == {"ok": False, "error": "No connection to GitHub."}
    assert api.poll()["update"] == "9.0.0"  # what was found before stays offered


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_update_extract(tmp_path):
    data = _zip({"raidpilot/version.py": "VERSION='9'", "START.bat": "x", "other/thing.exe": "x", "bad.exe": "x"})
    assert updater.extract_source(data, tmp_path) == 2
    assert (tmp_path / "raidpilot" / "version.py").exists() and not (tmp_path / "bad.exe").exists()
    for bad in ("../away.py", "raidpilot/../../away.py", "/abs.py", "C:/x.py"):
        with pytest.raises(updater.UpdateError):
            updater.extract_source(_zip({"raidpilot/version.py": "", bad: "x"}), tmp_path)


def test_update_download_checks():
    good = {"url": f"https://github.com/{updater.REPO}/releases/download/v2/a.zip",
            "digest": "sha256:" + hashlib.sha256(b"content").hexdigest()}
    opener = lambda *a, **k: io.BytesIO(b"content")
    assert updater.download(good, opener) == b"content"
    for bad in (dict(good, url="https://evil.example/a.zip"), dict(good, url="http://github.com/x"),
                dict(good, digest="sha256:00")):
        with pytest.raises(updater.UpdateError):
            updater.download(bad, opener)
    assert updater.is_newer("v2.0.1", "2.0.0") and not updater.is_newer("2.0", "2.0.0")


def test_purchase_dialog_is_never_confirmed(ocr):
    image = np.full((900, 1600, 3), 220, np.uint8)
    for text, y in (("Not enough Gold!", 320), ("Buy missing resources?", 400)):
        cv2.putText(image, text, (500, y), cv2.FONT_HERSHEY_DUPLEX, 1.3, (20, 20, 20), 2, cv2.LINE_AA)
    assert Screen(image, ocr).shows_gems()


def test_raw_screenshot_is_decoded():
    import struct

    pixels = np.zeros((4, 6, 4), np.uint8)
    pixels[..., 0] = 200  # red
    for header in (struct.pack("<III", 6, 4, 1), struct.pack("<IIII", 6, 4, 1, 0)):
        image = decode_raw(header + pixels.tobytes())
        assert image.shape == (4, 6, 3) and image[0, 0].tolist() == [0, 0, 200]
    warned = b"[Warning] Multiple displays were found\nUsing the first one\n" + header + pixels.tobytes()
    assert decode_raw(warned).shape == (4, 6, 3)
    assert decode_raw(b"\x89PNG" + bytes(40)) is None


def test_a_lost_leading_digit_is_repaired():
    from raidpilot.screen import _pick

    assert _pick(15_595_758, 5_595_758) == 15_595_758
    assert _pick(5_595_758, 15_595_758) == 15_595_758
    assert _pick(None, 42) == 42 and _pick(7_000, 9_000) == 7_000


def test_decorations_are_not_read_as_loot():
    from raidpilot.screen import parse_number

    assert parse_number("1 234 567") == 1234567
    assert parse_number("0O2x") is None and parse_number("676 890 2x") is None


def test_random_side_is_fully_visible():
    import random

    picked = {army.choose_sides("random", "dragon", random.Random(i))[0] for i in range(40)}
    assert picked == {"tl", "tr"}


def _storages(*points):
    return [storages.Storage("gold", x, y, 1.0) for x, y in points]


@pytest.mark.parametrize("side,points", [
    ("tl", [(0.34, 0.27), (0.38, 0.31)]),
    ("tr", [(0.66, 0.27), (0.62, 0.31)]),
    ("bl", [(0.29, 0.58), (0.32, 0.62)]),
    ("br", [(0.71, 0.58), (0.68, 0.62)]),
])
def test_most_loot_picks_the_edge_next_to_the_storages(side, points):
    assert storages.best_side(_storages(*points, (0.5, 0.45))) == side
    assert army.choose_sides("loot", "dragon", loot_side=side) == [side]


def test_most_loot_needs_enough_storages_and_prefers_a_fully_visible_edge():
    import random

    assert storages.best_side([]) is None and storages.best_side(_storages((0.3, 0.3))) is None
    # equally close to an upper and a lower edge: the upper one
    assert storages.best_side(_storages((0.30, 0.45), (0.30, 0.53))) == "tl"
    picked = {army.choose_sides("loot", "dragon", random.Random(i))[0] for i in range(40)}
    assert picked == {"tl", "tr"}, "nothing recognised: like Random Side"


def test_storages_are_only_looked_for_on_the_village():
    assert storages.on_base(0.5, 0.45) and storages.on_base(0.3, 0.35)
    for point in ((0.05, 0.2), (0.9, 0.1), (0.5, 0.9), (0.2, 0.15), (0.8, 0.75)):
        assert not storages.on_base(*point), point


def test_storage_model_runs_and_finds_nothing_on_an_empty_picture():
    empty = np.full((900, 1600, 3), (62, 104, 74), np.uint8)
    finder = storages.Finder()
    assert finder.find(empty) == [] and finder.find(cv2.resize(empty, (1280, 720))) == []
    assert storages.mark(empty, _storages((0.5, 0.5)), "tl").shape == empty.shape


def test_screenshot_ignores_warning_before_png():
    png = cv2.imencode(".png", np.zeros((4, 6, 3), np.uint8))[1].tobytes()
    adb = Adb()
    adb._raw = False
    adb._run = lambda *a, **k: b"[Warning] Multiple displays\n" + png
    assert adb.screenshot().shape == (4, 6, 3)


def test_zoom_methods_and_mouse_wheel(monkeypatch):
    adb = Adb("adb")
    sent = []
    monkeypatch.setattr(adb, "shell", lambda command, timeout=30: (sent.append(command), "" if "input" in command
                        or "sendevent" in command else GETEVENT)[1])
    assert adb.zoom_methods() == ["touch:0", "wheel"]
    assert adb.pinch((1600, 900), True, "wheel") and sent[-1].count("input mouse scroll 800 450 --axis VSCROLL,-1") == 6
    assert adb.pinch((1600, 900), False, "wheel") and "VSCROLL,1" in sent[-1]
    assert adb.zoom_out((1600, 900)) and sent[-1].startswith("sendevent ")
    adb.zoom_method = "wheel"
    assert adb.zoom_out((1600, 900)) and sent[-1].startswith("input mouse scroll")
