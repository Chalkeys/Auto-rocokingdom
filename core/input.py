import logging
import time

try:
    import win32gui
except ImportError:
    win32gui = None

import win32api
import win32con


_VK_MAP = {
    "esc": win32con.VK_ESCAPE,
    "tab": win32con.VK_TAB,
    "enter": win32con.VK_RETURN,
    "space": win32con.VK_SPACE,
}


def press_once(hwnd: int, key: str) -> None:
    if win32gui is None:
        logging.info("非 Windows 环境，模拟按键: %s", key)
        return

    vk_code = _VK_MAP.get(key.lower())
    if vk_code is None:
        if len(key) == 1:
            vk_code = win32api.VkKeyScan(key) & 0xFF
        else:
            logging.warning("不支持的按键字符串: %s", key)
            return

    scan_code = win32api.MapVirtualKey(vk_code, 0)

    lparam_down = 1 | (scan_code << 16)
    lparam_up = 1 | (scan_code << 16) | (1 << 30) | (1 << 31)

    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, lparam_down)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, lparam_up)


def click_at(hwnd: int, x: int, y: int) -> bool:
    if win32gui is None:
        logging.info("非 Windows 环境，模拟点击 (%d, %d)", x, y)
        return True

    try:
        screen_pos = win32gui.ClientToScreen(hwnd, (x, y))
        win32api.SetCursorPos(screen_pos)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        logging.info("已执行物理点击，屏幕坐标: %s", screen_pos)
        return True
    except Exception as e:
        logging.warning("执行物理点击失败: %s", e)
        return False
