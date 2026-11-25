"""Updates ueber GitHub-Releases. Laedt nur von GitHub und prueft die Pruefsumme, wenn vorhanden."""
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .version import REPO, VERSION

API = f"https://api.github.com/repos/{REPO}/releases/latest"
SOURCE_ASSET = "RaidPilot-source.zip"
SETUP_SUFFIX = "-Setup.exe"
ROOT_FILES = {"requirements.txt", "START.bat", "BUILD.bat", "README.md", "main.py"}
MAX_DOWNLOAD = 400 * 1024 * 1024


class UpdateError(Exception):
    pass


def version_tuple(text: str) -> tuple:
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts + [0] * (3 - len(parts)))


def is_newer(remote: str, local: str = VERSION) -> bool:
    return version_tuple(remote) > version_tuple(local)


def check(opener=urllib.request.urlopen):
    """Neuere Version als dict oder None."""
    request = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "RaidPilot"})
    try:
        with opener(request, timeout=10) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # noch keine Veroeffentlichung
            return None
        raise UpdateError(f"GitHub antwortet mit Fehler {exc.code}.") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError("Keine Verbindung zu GitHub.") from exc
    tag = str(release.get("tag_name", ""))
    if not tag or not is_newer(tag):
        return None
    return {
        "version": tag.lstrip("vV"),
        "notes": str(release.get("body") or "")[:600],
        "assets": [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "digest": a.get("digest") or ""}
                   for a in release.get("assets", [])],
    }


def pick_asset(info: dict, frozen: bool):
    for asset in info["assets"]:
        if (frozen and asset["name"].endswith(SETUP_SUFFIX)) or (not frozen and asset["name"] == SOURCE_ASSET):
            return asset
    raise UpdateError("Die neue Version enthält keine passende Datei.")


def download(asset: dict, opener=urllib.request.urlopen) -> bytes:
    url = urllib.parse.urlparse(asset["url"])
    if url.scheme != "https" or url.hostname != "github.com" or not url.path.startswith(f"/{REPO}/releases/download/"):
        raise UpdateError("Unerwartete Download-Adresse, Update abgebrochen.")
    request = urllib.request.Request(asset["url"], headers={"User-Agent": "RaidPilot"})
    try:
        with opener(request, timeout=60) as response:
            data = response.read(MAX_DOWNLOAD)
    except OSError as exc:
        raise UpdateError("Download fehlgeschlagen.") from exc
    digest = asset.get("digest", "")
    if digest.startswith("sha256:") and hashlib.sha256(data).hexdigest() != digest[7:]:
        raise UpdateError("Prüfsumme stimmt nicht, Update abgebrochen.")
    return data


def extract_source(data: bytes, target: Path) -> int:
    """Programmdateien aus dem Zip uebernehmen. Alles andere wird ignoriert."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UpdateError("Das Update-Paket ist beschädigt.") from exc
    files = {}
    for member in archive.infolist():
        if member.is_dir():
            continue
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in member.filename or ":" in member.filename:
            raise UpdateError("Das Update-Paket enthält ungültige Pfade.")
        if (len(path.parts) == 1 and path.name in ROOT_FILES) or (len(path.parts) > 1 and path.parts[0] == "raidpilot"):
            files[path] = archive.read(member)
    if PurePosixPath("raidpilot/version.py") not in files:
        raise UpdateError("Das Update-Paket ist unvollständig.")
    for path, content in files.items():
        destination = target.joinpath(*path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".neu")
        temporary.write_bytes(content)
        temporary.replace(destination)
    return len(files)


def install(info: dict) -> str:
    """Gibt 'exit' (Installer laeuft) oder 'restart' (Dateien ersetzt) zurueck."""
    frozen = bool(getattr(sys, "frozen", False))
    data = download(pick_asset(info, frozen))
    if frozen:
        setup = Path(tempfile.mkdtemp(prefix="raidpilot-")) / f"RaidPilot-{info['version']}{SETUP_SUFFIX}"
        setup.write_bytes(data)
        subprocess.Popen([str(setup), "/SILENT", "/CLOSEAPPLICATIONS"])
        return "exit"
    extract_source(data, Path(__file__).resolve().parent.parent)
    return "restart"
