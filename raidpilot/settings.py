"""Settings with defaults and validation."""
from . import store

FILE = "settings.json"
SCHEMA = 3

MODES = {"home": "Home Village", "builder": "Builder Base (not available yet)"}
ARMIES = {
    "dragon": "Dragon",
    "electric_dragon": "Electric Dragon",
    "super_dragon": "Super Dragon",
    "thrower": "Thrower",
    "meteor_golem": "Meteor Golem",
    "valkyrie": "Valkyrie",
    "sneaky_goblin": "Sneaky Goblin",
}
SPELLS = {"none": "None", "rage": "Rage Spells", "totem": "Totem Spells"}
STYLES = {
    "random": "Random Side",
    "loot": "Most Loot",
    "tl": "Top Left",
    "tr": "Top Right",
    "bl": "Bottom Left",
    "br": "Bottom Right",
    "all": "All Sides",
}
UNAVAILABLE = {"mode": ("builder",)}

DEFAULTS = {
    "mode": "home",
    "army": "dragon",
    "spell": "rage",
    "min_loot": 600_000,          # the opponent needs at least this much gold AND this much elixir
    "max_storage": 31_000_000,    # capacity of one storage resource
    "device": "",                 # empty = MuMu Player instance #0, started automatically
    "style": "random",
    "heroes": False,
    "siege": False,
    "event_troops": False,
    "walls": False,
    "stop_full": False,
    "donate": False,
    "webhook": "",
}
MAX_CAPACITY = 31_000_000
RANGES = {"min_loot": (0, 3_000_000), "max_storage": (1_000_000, MAX_CAPACITY)}
_CHOICES = {"mode": MODES, "army": ARMIES, "spell": SPELLS, "style": STYLES}
_WEBHOOKS = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")


def validate(key: str, value):
    """Returns the cleaned value or raises ValueError."""
    if key not in DEFAULTS:
        raise ValueError(f"Unknown setting: {key}")
    default = DEFAULTS[key]
    if key in _CHOICES:
        if value not in _CHOICES[key] or value in UNAVAILABLE.get(key, ()):
            raise ValueError(f"Invalid value for {key}: {value!r}")
        return value
    if key == "webhook":
        value = str(value).strip()
        if value and not value.startswith(_WEBHOOKS):
            raise ValueError("This is not a Discord webhook address.")
        return value
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        low, high = RANGES[key]
        return max(low, min(high, int(value)))
    return str(value).strip()


def load() -> dict:
    result = dict(DEFAULTS)
    stored = store.load(FILE, {})
    if stored.get("schema") not in (2, SCHEMA):  # files of version 1 used other defaults
        return result
    if stored["schema"] == 2 and stored.get("max_storage") == 24_000_000:
        stored["max_storage"] = MAX_CAPACITY  # that was the old end of the slider
    for key, value in stored.items():
        try:
            result[key] = validate(key, value)
        except (ValueError, TypeError):
            pass
    return result


def update(key: str, value) -> dict:
    current = load()
    current[key] = validate(key, value)
    store.save(FILE, {"schema": SCHEMA, **current})
    return current


def choices() -> dict:
    return {"mode": MODES, "army": ARMIES, "spell": SPELLS, "style": STYLES}
