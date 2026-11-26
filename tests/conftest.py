import pytest


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Every test gets its own data folder."""
    monkeypatch.setenv("RAIDPILOT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(scope="session")
def ocr():
    from raidpilot.ocr import Ocr

    return Ocr()
