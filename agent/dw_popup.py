"""
On-screen message popup and 'find my laptop' ring.

Windows: a standard message box that stays on top of other windows (exclusive-fullscreen
games may hide it until you Alt+Tab). The ring turns the volume up to max and beeps
until someone clicks OK, or for 60 seconds.
"""
import os
import subprocess
import sys
import threading
import time

IS_WIN = sys.platform == "win32"

MB_OK, MB_ICONINFO, MB_ICONWARN = 0x0, 0x40, 0x30
MB_SYSTEMMODAL, MB_SETFOREGROUND, MB_TOPMOST = 0x1000, 0x10000, 0x40000
TIMEOUT_RESULT = 32000


def show_box(text, title, warn=False, timeout_s=0):
    """Blocking. Returns 'ok' when clicked, 'timeout' if it closed by itself."""
    if not IS_WIN:
        try:
            subprocess.run(["notify-send", title, text], timeout=5)
        except Exception:
            print(f"[{title}] {text}")
        return "ok"
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32")
    flags = MB_OK | (MB_ICONWARN if warn else MB_ICONINFO) | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST
    if timeout_s:
        try:   # undocumented but present since Windows XP: closes the box after N ms
            fn = u32.MessageBoxTimeoutW
            fn.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT,
                           wintypes.WORD, wintypes.DWORD]
            r = fn(None, text, title, flags, 0, int(timeout_s * 1000))
            return "timeout" if r == TIMEOUT_RESULT else "ok"
        except AttributeError:
            pass
    u32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    u32.MessageBoxW(None, text, title, flags)
    return "ok"


def _max_volume():
    """Press 'volume up' 50 times (also unmutes). No audio libraries needed."""
    if not IS_WIN:
        return
    import ctypes
    u32 = ctypes.WinDLL("user32")
    VK_VOLUME_UP, KEYUP = 0xAF, 0x2
    for _ in range(50):
        u32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
        u32.keybd_event(VK_VOLUME_UP, 0, KEYUP, 0)


def _beep_until(stop, seconds):
    end = time.time() + seconds
    if IS_WIN:
        import winsound
        while not stop.is_set() and time.time() < end:
            winsound.Beep(1900, 280)
            winsound.Beep(2600, 280)
    else:
        while not stop.is_set() and time.time() < end:
            sys.stdout.write("\a")
            sys.stdout.flush()
            stop.wait(0.5)


def ring(seconds=60):
    """Blocking. Returns 'found' if someone clicked OK, else 'timeout'."""
    stop = threading.Event()
    _max_volume()
    beeper = threading.Thread(target=_beep_until, args=(stop, seconds), daemon=True)
    beeper.start()
    result = show_box("🔔 Found me!\n\nClick OK to stop the ringing.",
                      "DeviceWatch - Find my laptop", warn=True, timeout_s=seconds)
    stop.set()
    beeper.join(2)
    return "found" if result == "ok" else "timeout"
