import hashlib
import io
import zipfile

import cv2
import numpy as np
import pytest

from raidpilot import army, layout, settings, store, templates, updater, zoom
from raidpilot.adb import Adb, decode_raw
from raidpilot.api import Api
from raidpilot.mumu import Mumu, MumuError
from raidpilot.screen import Screen, label_matches, parse_number

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
    assert settings.update("max_storage", 99_000_000)["max_storage"] == 24_000_000
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
        ("troop", 14), ("event", 30), ("siege", 1), ("hero", None), ("hero", None), ("spell", 5)]
    assert [s.index for s in army.choose_spells(shot.image, slots, "rage")] == [5]
    assert army.choose_spells(shot.image, slots, "none") == []
    assert shot.loot() == (100_000, 120_000, 800)


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
    assert shot.player_name() == "TestChief" and shot.free_builders() == 1
    game.state = "welcome"
    assert not Screen(game.render(), ocr).home()


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


def test_decorations_are_not_read_as_loot():
    from raidpilot.screen import parse_number

    assert parse_number("1 234 567") == 1234567
    assert parse_number("0O2x") is None and parse_number("676 890 2x") is None


def test_random_side_is_fully_visible():
    import random

    picked = {army.choose_sides("random", "dragon", random.Random(i))[0] for i in range(40)}
    assert picked == {"tl", "tr"}


def test_screenshot_ignores_warning_before_png():
    png = cv2.imencode(".png", np.zeros((4, 6, 3), np.uint8))[1].tobytes()
    adb = Adb()
    adb._raw = False
    adb._run = lambda *a, **k: b"[Warning] Multiple displays\n" + png
    assert adb.screenshot().shape == (4, 6, 3)
