"""Two-finger gestures through ADB 'sendevent' (Linux multi-touch protocol)."""
import re
from dataclasses import dataclass

# Linux input event codes
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_MT_REPORT = 0, 2
BTN_TOUCH = 330
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR, ABS_MT_X, ABS_MT_Y, ABS_MT_TRACKING_ID, ABS_MT_PRESSURE = 47, 48, 53, 54, 57, 58


@dataclass
class TouchDevice:
    path: str
    max_x: int
    max_y: int
    slots: bool          # protocol B (slots) or A (SYN_MT_REPORT)
    touch_key: bool
    pressure: bool = False
    name: str = ""


def parse_touch_devices(output: str) -> list:
    """Multi-touch devices from 'getevent -pl'."""
    devices = []
    for block in re.split(r"(?m)^add device \d+: ", output):
        head = block.split("\n", 1)[0].strip()
        if not head.startswith("/dev/input/"):
            continue
        x = re.search(r"ABS_MT_POSITION_X\s*:.*?max (\d+)", block)
        y = re.search(r"ABS_MT_POSITION_Y\s*:.*?max (\d+)", block)
        if not x or not y:
            continue
        name = re.search(r'name:\s*"([^"]*)"', block)
        devices.append(TouchDevice(
            head, int(x.group(1)), int(y.group(1)), "ABS_MT_SLOT" in block, "BTN_TOUCH" in block,
            "ABS_MT_PRESSURE" in block, name.group(1) if name else ""))
    return devices


def to_device(device: TouchDevice, point, size) -> tuple:
    """Screen pixel -> touch coordinates. Handles panels that are mounted in portrait."""
    (x, y), (width, height) = point, size
    if (device.max_x < device.max_y) != (width < height):
        # Rotated by 90 degrees: the panel's x runs along the screen's height
        tx = (height - 1 - y) / max(1, height - 1)
        ty = x / max(1, width - 1)
    else:
        tx = x / max(1, width - 1)
        ty = y / max(1, height - 1)
    return int(round(tx * device.max_x)), int(round(ty * device.max_y))


def gesture_events(device: TouchDevice, paths: list, size) -> list:
    """paths: one list of screen points per finger, all of the same length."""
    events = []
    steps = len(paths[0])
    for step in range(steps):
        for finger, path in enumerate(paths):
            x, y = to_device(device, path[step], size)
            if device.slots:
                events.append((EV_ABS, ABS_MT_SLOT, finger))
            if step == 0 or not device.slots:
                events.append((EV_ABS, ABS_MT_TRACKING_ID, finger + 1 if device.slots else finger))
            events.append((EV_ABS, ABS_MT_X, x))
            events.append((EV_ABS, ABS_MT_Y, y))
            if step == 0 and device.pressure:
                events.append((EV_ABS, ABS_MT_PRESSURE, 50))
            if not device.slots:
                events.append((EV_SYN, SYN_MT_REPORT, 0))
        if step == 0 and device.touch_key:
            events.append((EV_KEY, BTN_TOUCH, 1))
        events.append((EV_SYN, SYN_REPORT, 0))
    # Lift both fingers
    if device.slots:
        for finger in range(len(paths)):
            events.append((EV_ABS, ABS_MT_SLOT, finger))
            events.append((EV_ABS, ABS_MT_TRACKING_ID, -1))
    else:
        events.append((EV_SYN, SYN_MT_REPORT, 0))
    if device.touch_key:
        events.append((EV_KEY, BTN_TOUCH, 0))
    events.append((EV_SYN, SYN_REPORT, 0))
    return events


def shell_script(device: TouchDevice, events: list) -> str:
    return ";".join(f"sendevent {device.path} {t} {c} {v}" for t, c, v in events)


def pinch_paths(size, zoom_out: bool = True, steps: int = 10) -> list:
    """Two fingers moving towards the middle (zoom out) or apart (zoom in)."""
    width, height = size
    far, near = 0.30, 0.06
    start, end = (far, near) if zoom_out else (near, far)
    left, right = [], []
    for i in range(steps):
        d = start + (end - start) * i / (steps - 1)
        left.append((width * (0.5 - d), height * 0.45))
        right.append((width * (0.5 + d), height * 0.45))
    return [left, right]


def wheel_script(size, zoom_out: bool = True, ticks: int = 6) -> str:
    """The same with a mouse wheel (newer Android versions), for emulators that ignore the fingers."""
    command = f"input mouse scroll {size[0] // 2} {size[1] // 2} --axis VSCROLL,{-1 if zoom_out else 1}"
    return ";".join([command] * ticks)


def describe(method: str) -> str:
    return "the mouse wheel" if method == "wheel" else "the two-finger gesture"

