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
    "return_home": ((0.38, 0.77, 0.62, 0.95), ("Return Home", "Return")),
    "okay": ((0.15, 0.40, 0.85, 0.95), ("Okay", "OK")),
    "cancel": ((0.15, 0.40, 0.85, 0.95), ("Cancel",)),
    "reload": ((0.10, 0.35, 0.90, 0.95), ("Reload Game", "Reload", "Try Again", "Retry")),
    "upgrade": ((0.12, 0.64, 0.88, 1.00), ("Upgrade More", "Upgrade")),
    "confirm": ((0.25, 0.55, 0.95, 0.98), ("Confirm", "Okay", "Upgrade")),
    "donate": ((0.00, 0.08, 0.45, 0.92), ("Donate",)),
}
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
    "tl": ((0.135, 0.435), (0.375, 0.110)),
    "tr": ((0.625, 0.110), (0.865, 0.435)),
    "bl": ((0.135, 0.545), (0.300, 0.765)),
    "br": ((0.865, 0.540), (0.690, 0.775)),
}
CENTER = (0.505, 0.455)

# Areas with buttons or panels: troops are never tapped there
BLOCKED = (
    (0.00, 0.00, 0.17, 0.28),   # enemy name and loot
    (0.76, 0.00, 1.00, 0.22),   # own resources
    (0.42, 0.00, 0.58, 0.09),   # battle timer
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
