"""Einstellungen mit Standardwerten und Pruefung."""
import copy

from . import store

MODES = {"home": "Heimatdorf", "builder": "Bauarbeiterbasis (Beta)"}
ARMIES = {
    "all": "Alle Truppen",
    "dragon": "Drachen",
    "edrag": "Elektrodrachen",
    "barch": "Barbaren + Bogenschützen",
    "goblin": "Kobolde",
    "custom": "Nur erfasste Truppen",
}
SPELLS = {
    "rage": "Wutzauber",
    "lightning": "Blitzzauber",
    "freeze": "Frostzauber",
    "heal": "Heilzauber",
    "haste": "Hastzauber",
    "none": "Keine Zauber",
}
STYLES = {
    "random": "Zufällige Seite",
    "tl": "Oben links",
    "tr": "Oben rechts",
    "bl": "Unten links",
    "br": "Unten rechts",
    "top": "Beide oberen Seiten",
    "all": "Alle vier Seiten",
}
ROLES = ("auto", "troop", "hero", "siege", "spell", "event", "skip")
MAX_SLOTS = 11

DEFAULTS = {
    "mode": "home",
    "army": "dragon",
    "spell": "rage",
    "min_loot": 600_000,
    "loot_rule": "sum",          # sum = Gold+Elixier zusammen, each = beide einzeln
    "max_storage": 20_000_000,
    "device": "",
    "adb_path": "",
    "style": "random",
    "heroes": True,
    "hero_ability_after": 12,
    "siege": False,
    "event_troops": False,
    "walls": False,
    "stop_full": False,
    "donate": False,
    "end_stale": 30,             # Sekunden ohne neue Beute -> Kampf beenden (0 = nie)
    "spell_delay": 7,
    "spell_slots": 1,            # nur noetig, wenn keine Helden in der Leiste sind
    "max_searches": 60,
    "max_attacks": 0,            # 0 = unbegrenzt
    "slot_roles": ["auto"] * MAX_SLOTS,
    "webhook": "",
}

_RANGES = {
    "min_loot": (0, 3_000_000),
    "max_storage": (500_000, 35_000_000),
    "hero_ability_after": (0, 90),
    "end_stale": (0, 120),
    "spell_delay": (0, 60),
    "spell_slots": (0, 6),
    "max_searches": (5, 500),
    "max_attacks": (0, 10_000),
}
_CHOICES = {"mode": MODES, "army": ARMIES, "spell": SPELLS, "style": STYLES, "loot_rule": ("sum", "each")}


def validate(key: str, value):
    """Gibt den bereinigten Wert zurueck oder wirft ValueError."""
    if key not in DEFAULTS:
        raise ValueError(f"Unbekannte Einstellung: {key}")
    default = DEFAULTS[key]
    if key in _CHOICES:
        if value not in _CHOICES[key]:
            raise ValueError(f"Ungültiger Wert für {key}: {value!r}")
        return value
    if key == "slot_roles":
        if not isinstance(value, list):
            raise ValueError("slot_roles muss eine Liste sein")
        roles = [r if r in ROLES else "auto" for r in value][:MAX_SLOTS]
        return roles + ["auto"] * (MAX_SLOTS - len(roles))
    if key == "webhook":
        value = str(value).strip()
        allowed = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")
        if value and not value.startswith(allowed):
            raise ValueError("Das ist keine Discord-Webhook-Adresse")
        return value
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        low, high = _RANGES[key]
        return max(low, min(high, int(value)))
    return str(value).strip()


def load() -> dict:
    result = copy.deepcopy(DEFAULTS)
    for key, value in store.load("settings.json", {}).items():
        try:
            result[key] = validate(key, value)
        except (ValueError, TypeError):
            pass
    return result


def update(key: str, value) -> dict:
    current = load()
    current[key] = validate(key, value)
    store.save("settings.json", current)
    return current


def choices() -> dict:
    return {"mode": MODES, "army": ARMIES, "spell": SPELLS, "style": STYLES}
