"""Where things are on the screen. All values are relative (0..1) to a 16:9 landscape picture and were
measured on a 1600x900 / 240 DPI MuMu Player instance with the English game."""

# name: (region x0, y0, x1, y1, accepted labels)
BUTTONS = {
    "home_battle": ((0.00, 0.88, 0.14, 1.00), ("Battle", "Attack!")),
    "home_build": ((0.86, 0.88, 1.00, 1.00), ("Build",)),
    "find_match": ((0.00, 0.35, 0.65, 0.98), ("Find a Match", "Find Match")),
    "army_attack": ((0.70, 0.80, 1.00, 0.98), ("Attack!", "Attack")),
    "next": ((0.76, 0.60, 1.00, 0.86), ("Next",)),
    "end_battle": ((0.00, 0.66, 0.20, 0.82), ("End Battle", "Surrender")),
    # multiplayer shows it at the bottom, practice battles a bit higher
    "return_home": ((0.36, 0.66, 0.66, 0.95), ("Return Home", "Return")),
    "okay": ((0.15, 0.40, 0.85, 0.95), ("Okay", "OK")),
    "cancel": ((0.15, 0.40, 0.85, 0.95), ("Cancel",)),
    "reload": ((0.10, 0.35, 0.90, 0.95), ("Reload Game", "Reload", "Try Again", "Retry")),
    "upgrade": ((0.12, 0.64, 0.88, 1.00), ("Upgrade More", "Upgrade")),
    "confirm": ((0.25, 0.55, 0.95, 0.98), ("Confirm", "Okay", "Upgrade")),
    "donate": ((0.00, 0.08, 0.45, 0.92), ("Donate",)),
}
# Buttons that never move: only their text line is read, which is many times faster than searching
SPOTS = {
    "home_battle": (0.025, 0.924, 0.110, 0.985),
    "home_build": (0.899, 0.924, 0.970, 0.983),
    "next": (0.890, 0.655, 0.975, 0.720),
    "end_battle": (0.019, 0.718, 0.128, 0.769),
    "find_match": (0.076, 0.684, 0.233, 0.747),
    "army_attack": (0.847, 0.858, 0.953, 0.918),
}
# Gold, elixir and dark elixir of the opponent
LOOT_ROWS = (  # narrow enough to leave out the "2x" decorations to the right
    (0.045, 0.1175, 0.147, 0.1635),
    (0.045, 0.1730, 0.147, 0.2190),
    (0.045, 0.2310, 0.147, 0.2780),
)
# Orange area of the Battle button: darker when a window lies on top of the village
BATTLE_PATCH = (0.0125, 0.939, 0.031, 0.967)
# Hero cards: art is colourful while the hero waits and grey once the hero is on the field
HERO_ART = (0.860, 0.950)
HERO_BAR = (0.783, 0.826)     # the green health bar is somewhere in here (the selected card is raised)
WARDEN_SWITCH = (0.940, 0.975)  # only the Grand Warden has the ground/air switch at the bottom right
# Your own storages at the top right: gold, elixir (one line each)
STORAGE_ROWS = (
    (0.850, 0.027, 0.954, 0.078),
    (0.850, 0.096, 0.954, 0.147),
)
# These labels must match completely ("End Battle" is not "Battle")
EXACT = ("home_battle", "home_build")

REGIONS = {
    "loot": (0.00, 0.02, 0.30, 0.45),
    "result": (0.34, 0.36, 0.64, 0.68),
    "bonus": (0.66, 0.38, 0.86, 0.66),
    "home_storage": (0.76, 0.00, 1.00, 0.22),
    "player_name": (0.08, 0.05, 0.30, 0.10),
    "builders": (0.86, 0.72, 1.00, 0.82),
    "troop_bar": (0.00, 0.81, 1.00, 1.00),
    "popup": (0.10, 0.10, 0.90, 0.95),
    "builder_list": (0.22, 0.05, 0.85, 0.95),
    "donate_popup": (0.20, 0.05, 0.98, 0.95),
}

POINTS = {
    "builder_menu": (0.922, 0.765),
    "chat_open": (0.036, 0.500),
    "chat_close": (0.385, 0.455),
    "close_window": (0.966, 0.090),
}

# Deployment lines just outside the red boundary when the map is zoomed out completely
SIDES = {
    "tl": ((0.120, 0.428), (0.420, 0.052)),   # along the outer grass strip, outside the red line
    "tr": ((0.580, 0.052), (0.880, 0.428)),
    "bl": ((0.135, 0.545), (0.300, 0.765)),
    "br": ((0.865, 0.540), (0.690, 0.775)),
}
CENTER = (0.505, 0.455)

# Areas with buttons or panels: troops are never tapped there
BLOCKED = (
    (0.00, 0.00, 0.17, 0.28),   # enemy name and loot
    (0.76, 0.00, 1.00, 0.22),   # own resources
    (0.435, 0.00, 0.565, 0.10), # battle timer
    (0.00, 0.69, 0.14, 0.81),   # End Battle
    (0.81, 0.62, 1.00, 0.81),   # Next / damage
    (0.00, 0.80, 1.00, 1.00),   # troop bar
)

# Words that point to a purchase: such dialogs are never confirmed
PURCHASE_WORDS = ("gem", "gems", "buy", "purchase", "missing", "notenough", "insufficient")
OTHER_DEVICE_WORDS = ("anotherdevice", "otherdevice")
BREAK_WORDS = ("personalbreak", "takeabreak", "timeforabreak")
WALL_WORDS = ("wall",)


def blocked(x: float, y: float) -> bool:
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in BLOCKED)
