"""Packt die Quellversion: dist/RaidPilot-source.zip (zum Weitergeben und fuer Updates)."""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["START.bat", "BUILD.bat", "README.md", "requirements.txt", "main.py"]


def main():
    target = ROOT / "dist" / "RaidPilot-source.zip"
    target.parent.mkdir(exist_ok=True)
    package = [p for p in sorted((ROOT / "raidpilot").rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in [ROOT / name for name in FILES] + package:
            archive.write(path, path.relative_to(ROOT).as_posix())
    print(target)


if __name__ == "__main__":
    main()
