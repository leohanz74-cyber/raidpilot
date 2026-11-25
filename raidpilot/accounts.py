"""Lokale Profile. Alles bleibt auf diesem PC; Passwoerter werden nur als Hash gespeichert."""
import hashlib
import hmac
import secrets
import time

from . import store

FILE = "accounts.json"
ITERATIONS = 200_000


class AccountError(Exception):
    pass


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def _load() -> dict:
    data = store.load(FILE, {})
    data.setdefault("users", {})
    data.setdefault("remember", None)
    return data


def _remember(data: dict, key: str, remember: bool) -> None:
    if remember:
        token = secrets.token_hex(24)
        data["users"][key]["token"] = hashlib.sha256(token.encode()).hexdigest()
        data["remember"] = {"user": key, "token": token}
    else:
        data["remember"] = None


def sign_up(name: str, password: str, remember: bool = True) -> str:
    name = (name or "").strip()
    if not 3 <= len(name) <= 24:
        raise AccountError("Der Name braucht 3 bis 24 Zeichen.")
    if len(password or "") < 4:
        raise AccountError("Das Passwort braucht mindestens 4 Zeichen.")
    data = _load()
    key = name.casefold()
    if key in data["users"]:
        raise AccountError("Diesen Namen gibt es schon.")
    salt = secrets.token_bytes(16)
    data["users"][key] = {"name": name, "salt": salt.hex(), "hash": _hash(password, salt), "created": int(time.time())}
    _remember(data, key, remember)
    store.save(FILE, data)
    return name


def sign_in(name: str, password: str, remember: bool = True) -> str:
    data = _load()
    key = (name or "").strip().casefold()
    user = data["users"].get(key)
    if not user or not hmac.compare_digest(user["hash"], _hash(password or "", bytes.fromhex(user["salt"]))):
        raise AccountError("Name oder Passwort stimmt nicht.")
    _remember(data, key, remember)
    store.save(FILE, data)
    return user["name"]


def auto_sign_in():
    data = _load()
    saved = data.get("remember")
    if not saved:
        return None
    user = data["users"].get(saved.get("user"))
    digest = hashlib.sha256(str(saved.get("token", "")).encode()).hexdigest()
    if user and hmac.compare_digest(user.get("token", ""), digest):
        return user["name"]
    return None


def sign_out() -> None:
    data = _load()
    data["remember"] = None
    store.save(FILE, data)


def created_at(name: str) -> int:
    return _load()["users"].get(name.casefold(), {}).get("created", 0)


def has_users() -> bool:
    return bool(_load()["users"])
