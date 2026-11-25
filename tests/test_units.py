import hashlib
import io
import zipfile

import pytest

from raidpilot import accounts, army, layout, settings, store, templates, updater
from raidpilot.adb import Adb
from raidpilot.screen import Screen, label_matches, parse_number

from .fakegame import FakeGame


def test_numbers():
    assert parse_number("1 234 567") == 1_234_567
    assert parse_number("987.654") == 987_654
    assert parse_number("12O 5OO") == 120_500
    assert parse_number("Available Loot:") is None
    assert parse_number("") is None


def test_labels():
    assert label_matches("Zuruck", "Zurück")
    assert label_matches("EndBattle", "End Battle")
    assert label_matches("Find a Matcn", "Find a Match")
    assert not label_matches("Shop", "Attack")
    assert not label_matches("Attack Log", "Next")


def test_settings_are_validated():
    assert settings.update("min_loot", 99_000_000)["min_loot"] == 3_000_000
    assert settings.update("slot_roles", ["hero", "quatsch"])["slot_roles"][:3] == ["hero", "auto", "auto"]
    with pytest.raises(ValueError):
        settings.update("style", "diagonal")
    with pytest.raises(ValueError):
        settings.update("webhook", "https://example.com/x")
    store.save("settings.json", {"min_loot": "abc", "army": "goblin"})
    assert settings.load()["min_loot"] == settings.DEFAULTS["min_loot"]
    assert settings.load()["army"] == "goblin"


def test_broken_file_is_kept(home):
    (home / "settings.json").write_text("{kaputt")
    assert settings.load()["mode"] == "home"
    assert (home / "settings.defekt").exists()


def test_accounts(home):
    accounts.sign_up("Leo", "geheim123")
    assert "geheim123" not in (home / "accounts.json").read_text()
    assert accounts.auto_sign_in() == "Leo"
    with pytest.raises(accounts.AccountError):
        accounts.sign_up("leo", "anderes")
    with pytest.raises(accounts.AccountError):
        accounts.sign_in("Leo", "falsch")
    assert accounts.sign_in("LEO", "geheim123", remember=False) == "Leo"
    assert accounts.auto_sign_in() is None


def test_device_list():
    out = "List of devices attached\nemulator-5554\toffline\n127.0.0.1:16384\tdevice\n\n"
    assert Adb.parse_devices(out) == [{"serial": "emulator-5554", "state": "offline"},
                                      {"serial": "127.0.0.1:16384", "state": "device"}]


def test_deploy_points_stay_on_screen():
    for name in layout.SIDES:
        for x, y in army.line_points(layout.sides(), [name], 30, outward=0.2):
            assert 0 < x < 1 and 0 < y <= 0.79
    assert len(army.line_points(layout.sides(), ["tl", "tr", "br", "bl"], 11)) == 11


def test_custom_side_is_clamped():
    layout.set_side("tl", (-1, 2), (0.3, 0.2))
    assert layout.sides()["tl"][0] == (0.01, 0.80)
    layout.reset_sides()
    assert layout.sides()["tl"] == layout.SIDES["tl"]


def test_troop_template_limits_deploy(ocr):
    game = FakeGame()
    game.state = "scout"
    shot = Screen(game.render(), ocr)
    templates.add("event", "Event", shot.image, (170 / 1280, 640 / 720, 230 / 1280, 700 / 720))
    slots = army.assign_roles(shot, army.detect_slots(shot), settings.load())
    assert slots[0].role == "event"
    templates.remove(templates.index()[0]["file"])
    assert templates.index() == []


def test_own_button_template(ocr):
    game = FakeGame()
    shot = Screen(game.render(), ocr)
    templates.add("button", "next", shot.image, (20 / 1280, 615 / 720, 200 / 1280, 685 / 720))
    point = Screen(shot.image, ocr).button("next")
    assert point and abs(point[0] - 110) < 5 and abs(point[1] - 650) < 5


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_update_extract(tmp_path):
    data = _zip({"raidpilot/version.py": "VERSION='9'", "START.bat": "x", "fremd/ding.exe": "x", "boese.exe": "x"})
    assert updater.extract_source(data, tmp_path) == 2
    assert (tmp_path / "raidpilot" / "version.py").exists() and not (tmp_path / "boese.exe").exists()
    for bad in ("../weg.py", "raidpilot/../../weg.py", "/abs.py", "C:/x.py"):
        with pytest.raises(updater.UpdateError):
            updater.extract_source(_zip({"raidpilot/version.py": "", bad: "x"}), tmp_path)


def test_update_download_checks(monkeypatch):
    good = {"url": f"https://github.com/{updater.REPO}/releases/download/v2/a.zip",
            "digest": "sha256:" + hashlib.sha256(b"inhalt").hexdigest()}
    opener = lambda *a, **k: io.BytesIO(b"inhalt")
    assert updater.download(good, opener) == b"inhalt"
    for bad in (dict(good, url="https://evil.example/a.zip"), dict(good, url="http://github.com/x"),
                dict(good, digest="sha256:00")):
        with pytest.raises(updater.UpdateError):
            updater.download(bad, opener)
    assert updater.is_newer("v1.0.1", "1.0.0") and not updater.is_newer("1.0", "1.0.0")


def test_purchase_dialog_is_never_confirmed(ocr):
    import cv2
    import numpy as np

    image = np.full((720, 1280, 3), 220, np.uint8)
    for text, y in (("Not enough Gold!", 250), ("Buy missing resources?", 320)):
        cv2.putText(image, text, (400, y), cv2.FONT_HERSHEY_DUPLEX, 1.1, (20, 20, 20), 2, cv2.LINE_AA)
    assert Screen(image, ocr).shows_gems()


def test_screenshot_ignores_warning_before_png():
    import cv2
    import numpy as np

    png = cv2.imencode(".png", np.zeros((4, 6, 3), np.uint8))[1].tobytes()
    adb = Adb()
    adb._run = lambda *a, **k: b"[Warning] Multiple displays\n" + png
    assert adb.screenshot().shape == (4, 6, 3)
