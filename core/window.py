import ctypes
import logging
from typing import List, Optional, Tuple

from config import CONFIG

try:
    import win32gui
except ImportError:
    win32gui = None

# DPI Awareness
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass


def find_all_windows_by_keyword(keyword: str) -> List[Tuple[int, str]]:
    """返回所有标题包含 keyword 的可见窗口，列表元素为 (hwnd, title)。"""
    if win32gui is None:
        return []
    results: List[Tuple[int, str]] = []
    keyword_lc = keyword.lower()

    def _handler(hwnd: int, _ctx: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title and keyword_lc in title.lower():
            results.append((hwnd, title))

    win32gui.EnumWindows(_handler, None)
    return results


def find_window_by_keyword(keyword: str) -> Optional[int]:
    if win32gui is None:
        return 1
    keyword_lc = keyword.lower()
    result_hwnd: Optional[int] = None

    def _enum_handler(hwnd: int, _ctx: object) -> None:
        nonlocal result_hwnd
        if result_hwnd is not None:
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        if keyword_lc in title.lower():
            result_hwnd = hwnd

    win32gui.EnumWindows(_enum_handler, None)
    return result_hwnd


def get_client_rect_on_screen(hwnd: int) -> Tuple[int, int, int, int]:
    if win32gui is None:
        return 0, 0, CONFIG.expected_window_width, CONFIG.expected_window_height
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    client_w = right - left
    client_h = bottom - top
    screen_left, screen_top = win32gui.ClientToScreen(hwnd, (0, 0))
    return screen_left, screen_top, client_w, client_h
