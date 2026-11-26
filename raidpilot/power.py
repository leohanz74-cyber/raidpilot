"""Windows power and priority settings of the program."""
import sys

_CONTINUOUS = 0x80000000
_SYSTEM_REQUIRED = 0x00000001
_BELOW_NORMAL = 0x00004000


def _kernel():
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.WinDLL("kernel32")


def keep_awake(on: bool) -> bool:
    """While on, Windows does not go to sleep by itself; the screen may still turn off.
    Counts for the calling thread, so call it from the thread that does the work.
    True if Windows accepted it."""
    kernel = _kernel()
    if kernel is None:
        return False
    import ctypes

    kernel.SetThreadExecutionState.argtypes = [ctypes.c_uint32]
    kernel.SetThreadExecutionState.restype = ctypes.c_uint32
    return bool(kernel.SetThreadExecutionState(_CONTINUOUS | (_SYSTEM_REQUIRED if on else 0)))


def lower_priority() -> None:
    """The emulator goes first when the processor is busy, so the game does not lag."""
    kernel = _kernel()
    if kernel is None:
        return
    import ctypes

    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.SetPriorityClass(kernel.GetCurrentProcess(), _BELOW_NORMAL)
