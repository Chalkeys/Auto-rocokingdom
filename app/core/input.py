import random
import time

import win32api
import win32con
import win32gui


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


def _rand_delay(lo: float = 0.03, hi: float = 0.08) -> float:
    return random.uniform(lo, hi)


def press_once(hwnd: int, key: str) -> None:
    vk = _VK_MAP.get(key.lower())
    if vk is None:
        if len(key) == 1:
            vk = win32api.VkKeyScan(key) & 0xFF
        else:
            return

    scan = win32api.MapVirtualKey(vk, 0)
    ext = 1 << 24 if vk in _EXTENDED_VK else 0

    lp_down = 1 | (scan << 16) | ext
    lp_up   = 1 | (scan << 16) | ext | (1 << 30) | (1 << 31)

    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lp_down)
    time.sleep(_rand_delay(0.04, 0.10))
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, lp_up)


def click_at(hwnd: int, x: int, y: int) -> bool:
    try:
        jx = x + random.randint(-2, 2)
        jy = y + random.randint(-2, 2)
        lp = (jy << 16) | (jx & 0xFFFF)

        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
        time.sleep(_rand_delay(0.05, 0.12))
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
        return True
    except Exception:
        return False
