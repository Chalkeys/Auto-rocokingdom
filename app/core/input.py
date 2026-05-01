import ctypes
import ctypes.wintypes
import random
import time

import win32api
import win32con
import win32gui

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

_EXTENDED_VK = {
    win32con.VK_RCONTROL, win32con.VK_RMENU,
    win32con.VK_INSERT, win32con.VK_DELETE,
    win32con.VK_HOME, win32con.VK_END,
    win32con.VK_PRIOR, win32con.VK_NEXT,
    win32con.VK_LEFT, win32con.VK_UP,
    win32con.VK_RIGHT, win32con.VK_DOWN,
    win32con.VK_NUMLOCK, win32con.VK_SNAPSHOT,
    win32con.VK_DIVIDE, win32con.VK_LWIN, win32con.VK_RWIN,
}

_VK_MAP = {
    "esc": win32con.VK_ESCAPE,
    "tab": win32con.VK_TAB,
    "enter": win32con.VK_RETURN,
    "space": win32con.VK_SPACE,
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


def _send_input(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    ctypes.windll.user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))


def _rand_delay(lo: float = 0.03, hi: float = 0.08) -> float:
    return random.uniform(lo, hi)


def _attach(hwnd: int):
    """Attach current thread to hwnd's thread and redirect focus. Returns context tuple."""
    user32 = ctypes.windll.user32
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = target_tid != cur_tid and bool(
        user32.AttachThreadInput(target_tid, cur_tid, True)
    )
    prev_focus = user32.GetFocus()
    user32.SetFocus(hwnd)
    return target_tid, cur_tid, prev_focus, attached


def _detach(ctx: tuple) -> None:
    target_tid, cur_tid, prev_focus, attached = ctx
    user32 = ctypes.windll.user32
    if prev_focus:
        user32.SetFocus(prev_focus)
    if attached:
        user32.AttachThreadInput(target_tid, cur_tid, False)


def press_once(hwnd: int, key: str) -> None:
    vk = _VK_MAP.get(key.lower())
    if vk is None:
        if len(key) == 1:
            vk = win32api.VkKeyScan(key) & 0xFF
        else:
            return

    scan = win32api.MapVirtualKey(vk, 0)
    ext = KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED_VK else 0

    down = INPUT()
    down.type = INPUT_KEYBOARD
    down.union.ki.wVk = vk
    down.union.ki.wScan = scan
    down.union.ki.dwFlags = KEYEVENTF_SCANCODE | ext

    up = INPUT()
    up.type = INPUT_KEYBOARD
    up.union.ki.wVk = vk
    up.union.ki.wScan = scan
    up.union.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP | ext

    ctx = _attach(hwnd)
    try:
        _send_input(down)
        time.sleep(_rand_delay(0.04, 0.10))
        _send_input(up)
    finally:
        _detach(ctx)


def click_at(hwnd: int, x: int, y: int) -> bool:
    try:
        jx = x + random.randint(-2, 2)
        jy = y + random.randint(-2, 2)
        sx, sy = win32gui.ClientToScreen(hwnd, (jx, jy))
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        abs_x = int(sx * 65535 / (sw - 1))
        abs_y = int(sy * 65535 / (sh - 1))

        move = INPUT()
        move.type = INPUT_MOUSE
        move.union.mi.dx = abs_x
        move.union.mi.dy = abs_y
        move.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE

        down = INPUT()
        down.type = INPUT_MOUSE
        down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN

        up = INPUT()
        up.type = INPUT_MOUSE
        up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP

        ctx = _attach(hwnd)
        try:
            _send_input(move)
            time.sleep(_rand_delay(0.05, 0.12))
            _send_input(down)
            time.sleep(_rand_delay(0.04, 0.09))
            _send_input(up)
        finally:
            _detach(ctx)
        return True
    except Exception:
        return False
