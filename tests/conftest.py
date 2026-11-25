import pytest


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Jeder Test bekommt einen eigenen Datenordner."""
    monkeypatch.setenv("RAIDPILOT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(scope="session")
def ocr():
    from raidpilot.ocr import Ocr

    return Ocr()
