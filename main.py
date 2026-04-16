import glob
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import keyboard
import mss
import numpy as np
import ctypes
try:
    import win32gui
    import win32ui
except ImportError:
    win32gui = None
    win32ui = None

import win32api
import win32con

# DPI Awareness
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

from config import CONFIG


AUDIT_LOGGER_NAME = "audit"


@dataclass
class Template:
    name: str
    image: np.ndarray


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler("logs/runtime.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    # Dedicated audit log for action traceability.
    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    audit_logger.handlers.clear()
    audit_handler = logging.FileHandler("logs/audit.log", encoding="utf-8")
    audit_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    audit_logger.addHandler(audit_handler)


def log_audit(event: str, **payload: object) -> None:
    data = {"event": event, **payload}
    logging.getLogger(AUDIT_LOGGER_NAME).info(
        json.dumps(data, ensure_ascii=False, sort_keys=True)
    )


def normalize_poll_interval(interval: float) -> float:
    if interval <= 0:
        logging.warning("poll_interval_sec <= 0, fallback to 5.0")
        return 5.0
    if interval > 5.0:
        logging.warning("poll_interval_sec > 5.0, clamped to 5.0")
        return 5.0
    return interval


def find_window_by_keyword(keyword: str) -> Optional[int]:
    if win32gui is None:
        # Mock for non-Windows testing (e.g. testing logic on Linux)
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
        # Mock for non-Windows testing
        return 0, 0, CONFIG.expected_window_width, CONFIG.expected_window_height
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    client_w = right - left
    client_h = bottom - top
    screen_left, screen_top = win32gui.ClientToScreen(hwnd, (0, 0))
    return screen_left, screen_top, client_w, client_h


def build_roi(left: int, top: int, width: int, height: int) -> Tuple[int, int, int, int]:
    # 该函数原本用于 MSS。现在改用 capture_window_bgr，ROI 逻辑已移入 run 循环内部。
    return left, top, width, height


def preprocess(image_bgr: np.ndarray) -> np.ndarray:
    # Always convert to gray
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    
    # If using edge match, perform Canny, otherwise simple blur is enough
    if CONFIG.use_edge_match:
        # User observation: edges might be too aggressive for simple buttons
        # Try a more standard Canny for consistency
        return cv2.Canny(gray, 100, 200)
    
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return gray


def load_templates() -> List[Template]:
    pattern = os.path.join(CONFIG.template_dir, CONFIG.template_pattern)
    paths = sorted(glob.glob(pattern))
    templates: List[Template] = []

    for path in paths:
        raw = cv2.imread(path)
        if raw is None:
            logging.warning("skip unreadable template: %s", path)
            continue
        # Use simple gray for yes.png if it's a simple button
        if "yes" in path.lower():
             processed = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        else:
             processed = preprocess(raw)
        templates.append(Template(name=os.path.basename(path), image=processed))

    if not templates:
        raise FileNotFoundError(
            "No template images found. Put PNG files into templates/ first."
        )

    logging.info("Loaded %d templates", len(templates))
    return templates


def capture_window_bgr(hwnd: int) -> np.ndarray:
    """
    通过 Windows API 直接抓取窗口内容，即使窗口被遮挡。
    """
    if win32gui is None or win32ui is None:
        raise ImportError("需要安装 pywin32 库 (pip install pywin32)")

    # 直接按客户区尺寸抓图，确保识别坐标与 click_at(client 坐标)一致。
    client_rect = win32gui.GetClientRect(hwnd)
    client_w = client_rect[2] - client_rect[0]
    client_h = client_rect[3] - client_rect[1]

    if client_w <= 0 or client_h <= 0:
        return np.zeros((1, 1, 3), dtype=np.uint8)

    hwndDC = win32gui.GetDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()

    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, client_w, client_h)

    saveDC.SelectObject(saveBitMap)

    # 3 = PW_CLIENTONLY(1) | PW_RENDERFULLCONTENT(2)
    # 优先抓客户区完整内容；失败则回退到 BitBlt。
    result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)
    
    # 如果 PrintWindow 失败（返回0），回退到 BitBlt
    if result != 1:
        saveDC.BitBlt((0, 0), (client_w, client_h), mfcDC, (0, 0), win32con.SRCCOPY)

    signedIntsArray = saveBitMap.GetBitmapBits(True)
    img = np.frombuffer(signedIntsArray, dtype='uint8')
    
    # 鲁棒性检查：确保数据长度匹配，不符合则补全
    expected_size = client_h * client_w * 4
    if len(img) != expected_size:
        # 如果长度不符，返回一个空图并记录警告
        logging.warning(f"Capture data size mismatch: expected {expected_size}, got {len(img)}")
        img = np.zeros(expected_size, dtype='uint8')

    img.shape = (client_h, client_w, 4)

    # 释放资源
    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)

    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def best_match_score(frame_processed: np.ndarray, templates: List[Template], scale: float = 1.0) -> Tuple[float, str, Tuple[int, int]]:
    best_score = -1.0
    best_name = ""
    best_loc = (0, 0)
    fh, fw = frame_processed.shape[:2]

    for tpl in templates:
        tpl_img = tpl.image
        # If running on non-reference resolution, resize template dynamically
        if abs(scale - 1.0) > 0.01:
            new_w = max(1, int(tpl_img.shape[1] * scale))
            new_h = max(1, int(tpl_img.shape[0] * scale))
            tpl_img = cv2.resize(tpl_img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        th, tw = tpl_img.shape[:2]
        if th > fh or tw > fw:
            continue
        result = cv2.matchTemplate(frame_processed, tpl_img, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = float(max_val)
            best_name = tpl.name
            # Center of the match
            best_loc = (max_loc[0] + tw // 2, max_loc[1] + th // 2)

    return best_score, best_name, best_loc


def best_yes_score_and_loc(frame_bgr: np.ndarray, templates: List[Template], scale: float) -> Tuple[float, Tuple[int, int]]:
    frame_edge = preprocess(frame_bgr)
    frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    fh, fw = frame_gray.shape[:2]

    best_score = -1.0
    best_loc = (0, 0)

    for tpl in templates:
        if "yes" not in tpl.name.lower():
            continue
        t_img = tpl.image
        if abs(scale - 1.0) > 0.01:
            t_img = cv2.resize(
                t_img,
                (max(1, int(t_img.shape[1] * scale)), max(1, int(t_img.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )

        th, tw = t_img.shape[:2]
        if th > fh or tw > fw:
            continue

        res_edge = cv2.matchTemplate(frame_edge, t_img, cv2.TM_CCOEFF_NORMED)
        res_gray = cv2.matchTemplate(frame_gray, t_img, cv2.TM_CCOEFF_NORMED)
        _, max_v_edge, _, max_l_edge = cv2.minMaxLoc(res_edge)
        _, max_v_gray, _, max_l_gray = cv2.minMaxLoc(res_gray)

        cur_v, cur_l = (max_v_edge, max_l_edge) if max_v_edge > max_v_gray else (max_v_gray, max_l_gray)
        if cur_v > best_score:
            best_score = float(cur_v)
            best_loc = (cur_l[0] + tw // 2, cur_l[1] + th // 2)

    return best_score, best_loc


def press_once(hwnd: int, key: str) -> None:
    if win32gui is None:
        logging.info("Mocking key press for non-Windows environment: %s", key)
        return
    
    # Handle special keys or length > 1
    if key.lower() == "esc":
        vk_code = win32con.VK_ESCAPE
    elif len(key) == 1:
        vk_code = win32api.VkKeyScan(key) & 0xFF
    else:
        logging.warning("Unsupported key string: %s", key)
        return

    # Map virtual key to scan code
    scan_code = win32api.MapVirtualKey(vk_code, 0)
    
    # Use PostMessage for more reliable background input
    lparam_down = 1 | (scan_code << 16)
    lparam_up = 1 | (scan_code << 16) | (1 << 30) | (1 << 31)
    
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, lparam_down)
    time.sleep(0.05)  # Brief delay to simulate human press duration
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, lparam_up)


def click_at(hwnd: int, x: int, y: int) -> bool:
    if win32gui is None:
        logging.info("Mocking click at (%d, %d)", x, y)
        return True
    
    # Convert client (x, y) to screen coordinates and do a physical click.
    try:
        screen_pos = win32gui.ClientToScreen(hwnd, (x, y))
        # Use win32api to perform a physical mouse click
        win32api.SetCursorPos(screen_pos)
        time.sleep(0.1)
        # mouse_event uses specific flags for down and up
        # LEFTDOWN = 0x0002, LEFTUP = 0x0004
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        logging.info("Performed physical click at screen pos %s", screen_pos)
        return True
    except Exception as e:
        logging.warning("Failed to perform physical click: %s", e)
        return False


def run() -> None:
    setup_logging()

    logging.info("Starting detector. Stop hotkey: %s", CONFIG.stop_hotkey)
    logging.info("This script is for authorized testing only.")

    print("\n请选择运行模式:")
    print("1: 聚能模式 (自动键入 X)")
    print("2: 逃跑模式 (自动键入 ESC 并点击确认)")
    print("有问题或新功能建议请提 issue。如果这个项目对你有帮助，欢迎点个 Star 支持一下。")
    print("\n[提示] 脚本支持自适应分辨率，推荐使用 2K（2560x1600 或 2560x1440）以获得更高识别精度。")
    print("分辨率越低 Score 可能越低；若识别异常，可在当前分辨率下重截 templates 进行适配。")
    print("[提示] 逃跑模式使用物理点击，请确保“是”按钮露出且不被其他窗口遮挡。")
    choice = input("请输入选项 (1 或 2): ").strip()
    mode = "battle" if choice != "2" else "escape"
    logging.info("已选择模式: %s", "聚能模式" if mode == "battle" else "逃跑模式")
    log_audit(
        "MODE_SELECTED",
        mode=mode,
        match_threshold=CONFIG.match_threshold,
        trigger_cooldown_sec=CONFIG.trigger_cooldown_sec,
        escape_click_method=CONFIG.escape_click_method,
    )

    templates = load_templates()
    interval = normalize_poll_interval(CONFIG.poll_interval_sec)

    hit_streak = 0
    miss_streak = 0
    in_battle_state = False
    last_trigger_time = 0.0

    with mss.mss() as sct:
        while True:
            # On Windows, monitor hotkey to stop
            if win32gui is not None:
                if keyboard.is_pressed(CONFIG.stop_hotkey):
                    logging.info("Stop hotkey pressed. Exiting.")
                    break
            
            hwnd = find_window_by_keyword(CONFIG.window_title_keyword)
            if hwnd is None:
                logging.warning("Game window not found: %s", CONFIG.window_title_keyword)
                time.sleep(interval)
                continue

            left, top, width, height = get_client_rect_on_screen(hwnd)
            if width <= 0 or height <= 0:
                logging.warning("Invalid window size: %sx%s", width, height)
                time.sleep(interval)
                continue

            # Calculate dynamic scale based on reference resolution
            scale = width / CONFIG.ref_width
            if abs(scale - 1.0) > 0.05:
                logging.debug("Scaling templates by factor: %.2f (width=%d)", scale, width)

            # --- 改动：使用 capture_window_bgr 代替 capture_bgr 以支持后台/遮挡抓取 ---
            # 1. 抓取全屏
            full_window_bgr = capture_window_bgr(hwnd)
            
            # 2. 从全屏中裁剪 ROI
            roi_left = int(width * CONFIG.roi_left_ratio)
            roi_top = int(height * CONFIG.roi_top_ratio)
            roi_w = int(width * CONFIG.roi_width_ratio)
            roi_h = int(height * CONFIG.roi_height_ratio)
            
            frame_bgr = full_window_bgr[roi_top:roi_top+roi_h, roi_left:roi_left+roi_w]
            frame_processed = preprocess(frame_bgr)
            # -------------------------------------------------------------------

            # Pass the scale factor for resolution independence
            score, name, center_loc = best_match_score(frame_processed, templates, scale=scale)
            is_hit = score >= CONFIG.match_threshold

            if is_hit:
                hit_streak += 1
                miss_streak = 0
            else:
                hit_streak = 0
                miss_streak += 1

            if not in_battle_state:
                detected = hit_streak >= CONFIG.required_hits
            else:
                detected = miss_streak < CONFIG.release_misses

            logging.info(
                "score=%.3f hit=%s hit_streak=%d miss_streak=%d tpl=%s",
                score,
                is_hit,
                hit_streak,
                miss_streak,
                name,
            )

            now = time.time()
            cooldown_ready = (now - last_trigger_time) >= CONFIG.trigger_cooldown_sec
            
            # Action logic based on mode
            if detected:
                # IMPORTANT: Only trigger if we actually matched a template (is_hit)
                # This prevents triggering on "miss_streak" logic when we haven't seen the target
                if is_hit and (now - last_trigger_time >= CONFIG.trigger_cooldown_sec):
                    if mode == "battle":
                        press_once(hwnd, CONFIG.press_key)
                        last_trigger_time = now
                        logging.info("Triggered key: %s (Continuous)", CONFIG.press_key)
                        log_audit(
                            "TRIGGER_BATTLE_KEY",
                            mode=mode,
                            key=CONFIG.press_key,
                            hwnd=hwnd,
                            score=round(score, 4),
                            template=name,
                            hit_streak=hit_streak,
                            miss_streak=miss_streak,
                            cooldown_sec=CONFIG.trigger_cooldown_sec,
                        )
                    elif mode == "escape":
                        press_once(hwnd, "esc")
                        logging.info("Triggered Escape")
                        log_audit(
                            "TRIGGER_ESCAPE_KEY",
                            mode=mode,
                            key="esc",
                            hwnd=hwnd,
                            score=round(score, 4),
                            template=name,
                            hit_streak=hit_streak,
                            miss_streak=miss_streak,
                            cooldown_sec=CONFIG.trigger_cooldown_sec,
                        )
                        
                        # Capture again to find "Yes" button in popup
                        button_clicked = False
                        yes_best_score = -1.0
                        yes_best_loc = (0, 0)
                        yes_threshold = CONFIG.match_threshold * 0.8
                        # Increase attempts for popup animation
                        for i in range(10):
                            time.sleep(0.3)
                            full_shot = capture_window_bgr(hwnd)
                            best_score_this_round, best_loc_this_round = best_yes_score_and_loc(
                                full_shot,
                                templates,
                                scale,
                            )

                            if best_score_this_round > yes_best_score:
                                yes_best_score = best_score_this_round
                                yes_best_loc = best_loc_this_round

                            if best_score_this_round >= yes_threshold:
                                cap_h, cap_w = full_shot.shape[:2]
                                click_x = best_loc_this_round[0]
                                click_y = best_loc_this_round[1]
                                if cap_w > 0 and cap_h > 0 and (cap_w != width or cap_h != height):
                                    click_x = int(round(best_loc_this_round[0] * width / cap_w))
                                    click_y = int(round(best_loc_this_round[1] * height / cap_h))
                                    click_x = max(0, min(width - 1, click_x))
                                    click_y = max(0, min(height - 1, click_y))
                                    logging.debug(
                                        "Click coord normalized: shot=%sx%s client=%sx%s raw=(%s,%s) mapped=(%s,%s)",
                                        cap_w,
                                        cap_h,
                                        width,
                                        height,
                                        best_loc_this_round[0],
                                        best_loc_this_round[1],
                                        click_x,
                                        click_y,
                                    )

                                click_ok = click_at(hwnd, click_x, click_y)
                                button_clicked = click_ok
                                if click_ok:
                                    log_audit(
                                        "ESCAPE_YES_CLICK_SUCCESS",
                                        mode=mode,
                                        hwnd=hwnd,
                                        score=round(score, 4),
                                        template=name,
                                        yes_score=round(best_score_this_round, 4),
                                        threshold=round(yes_threshold, 4),
                                        click_x=click_x,
                                        click_y=click_y,
                                        click_method="physical",
                                        attempt=i + 1,
                                    )
                                    break
                        
                        if not button_clicked:
                            logging.warning("Could not find confirmation button 'yes.png' after ESC")
                            log_audit(
                                "ESCAPE_YES_CLICK_FAILED",
                                mode=mode,
                                hwnd=hwnd,
                                score=round(score, 4),
                                template=name,
                                best_yes_score=round(yes_best_score, 4),
                                best_yes_x=yes_best_loc[0],
                                best_yes_y=yes_best_loc[1],
                                threshold=round(yes_threshold, 4),
                                click_method="physical",
                            )
                        
                        # Use a longer cooldown for escape to prevent ESC spamming while dialog is closing
                        last_trigger_time = now + 2.0 

            in_battle_state = detected
            time.sleep(interval)


if __name__ == "__main__":
    run()
