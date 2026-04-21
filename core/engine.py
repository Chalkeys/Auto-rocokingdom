import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import mss

from config import CONFIG
from core.capture import capture_window_bgr
from core.logger import log_audit
from core.vision import (
    Template,
    best_match_score,
    load_templates,
    normalize_poll_interval,
    normalize_template_name,
    preprocess,
)
from core.window import find_window_by_keyword, get_client_rect_on_screen
from modes.base import BaseMode, BattleEvent


class Engine:
    def __init__(
        self,
        mode: BaseMode,
        stop_event: Optional[threading.Event] = None,
        status_callback: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        self._mode = mode
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._status_callback = status_callback

    def _push_status(self, **kwargs: object) -> None:
        if self._status_callback is not None:
            self._status_callback(kwargs)

    def run(self) -> None:
        logging.info("检测器已启动，按 Ctrl+C 退出。")
        logging.info("本脚本仅用于授权测试。")

        templates = load_templates()
        interval = normalize_poll_interval(CONFIG.poll_interval_sec)
        chat_template_key = normalize_template_name(CONFIG.chat_template_name)
        capture_template_key = normalize_template_name(CONFIG.capture_template_name)
        pollute_capture_template_key = normalize_template_name(CONFIG.pollute_capture_template_name)
        loaded_template_keys = {normalize_template_name(t.name) for t in templates}

        if chat_template_key not in loaded_template_keys:
            logging.warning(
                "聊天模板未加载: 配置=%s 已加载=%s",
                CONFIG.chat_template_name,
                sorted(loaded_template_keys),
            )
            log_audit("聊天模板缺失", 配置=CONFIG.chat_template_name)
        else:
            logging.info("聊天模板已加载: %s", chat_template_key)

        if self._mode.name == "smart":
            if capture_template_key not in loaded_template_keys:
                logging.warning(
                    "智能模式缺少普通战斗模板: 配置=%s",
                    CONFIG.capture_template_name,
                )
            if pollute_capture_template_key not in loaded_template_keys:
                logging.warning(
                    "智能模式缺少污染战斗模板: 配置=%s",
                    CONFIG.pollute_capture_template_name,
                )

        hit_streak = 0
        miss_streak = 0
        in_battle_state = False
        last_trigger_time = 0.0
        battle_count = 0
        pollute_count = 0
        chat_detected_last = False

        try:
            import win32gui
        except ImportError:
            win32gui = None

        with mss.mss() as sct:
            while not self._stop_event.is_set():
                hwnd = find_window_by_keyword(CONFIG.window_title_keyword)
                if hwnd is None:
                    logging.warning("未找到游戏窗口: %s", CONFIG.window_title_keyword)
                    self._push_status(state="未找到游戏窗口")
                    time.sleep(interval)
                    continue

                left, top, width, height = get_client_rect_on_screen(hwnd)
                if width <= 0 or height <= 0:
                    logging.warning("窗口尺寸无效: %sx%s", width, height)
                    time.sleep(interval)
                    continue

                scale = width / CONFIG.ref_width
                if abs(scale - 1.0) > 0.05:
                    logging.debug("模板缩放系数: %.2f（窗口宽度=%d）", scale, width)

                full_window_bgr = capture_window_bgr(hwnd)

                roi_left = int(width * CONFIG.roi_left_ratio)
                roi_top = int(height * CONFIG.roi_top_ratio)
                roi_w = int(width * CONFIG.roi_width_ratio)
                roi_h = int(height * CONFIG.roi_height_ratio)

                roi_left = max(0, min(width - 1, roi_left))
                roi_top = max(0, min(height - 1, roi_top))
                roi_w = max(1, min(width - roi_left, roi_w))
                roi_h = max(1, min(height - roi_top, roi_h))

                frame_bgr = full_window_bgr[roi_top:roi_top + roi_h, roi_left:roi_left + roi_w]
                frame_processed = preprocess(frame_bgr)

                score, name, center_loc, all_matches = best_match_score(frame_processed, templates, scale=scale)

                action_score = -1.0
                action_template = ""
                for tpl_name, tpl_score in all_matches:
                    if normalize_template_name(tpl_name) == chat_template_key:
                        continue
                    if tpl_score > action_score:
                        action_score = tpl_score
                        action_template = tpl_name

                is_hit = action_score >= CONFIG.match_threshold

                chat_score = next(
                    (s for n, s in all_matches if normalize_template_name(n) == chat_template_key),
                    0.0,
                )
                chat_detected_current = chat_score >= CONFIG.match_threshold
                capture_score = next(
                    (s for n, s in all_matches if normalize_template_name(n) == capture_template_key),
                    0.0,
                )
                pollute_capture_score = next(
                    (s for n, s in all_matches if normalize_template_name(n) == pollute_capture_template_key),
                    0.0,
                )

                # Battle count via chat edge detection
                battle_start_by_chat = not chat_detected_last and chat_detected_current
                if battle_start_by_chat:
                    battle_count += 1
                    is_pollute_battle = pollute_capture_score > capture_score
                    if is_pollute_battle:
                        pollute_count += 1
                    logging.info(
                        "检测到新战斗，当前污染次数=%d（判型=%s, capture=%.3f, pollute_capture=%.3f）",
                        pollute_count,
                        "污染" if is_pollute_battle else "普通",
                        capture_score,
                        pollute_capture_score,
                    )
                    log_audit(
                        "战斗次数增加",
                        战斗次数=battle_count,
                        污染次数=pollute_count,
                    )

                    event = BattleEvent(
                        hwnd=hwnd,
                        templates=templates,
                        scale=scale,
                        battle_count=battle_count,
                        pollute_count=pollute_count,
                        capture_score=capture_score,
                        pollute_capture_score=pollute_capture_score,
                        window_width=width,
                        window_height=height,
                    )
                    self._mode.on_battle_start(event)

                chat_detected_last = chat_detected_current

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

                battle_start_by_state = (not in_battle_state) and detected
                battle_end_by_state = in_battle_state and (not detected)

                event = BattleEvent(
                    hwnd=hwnd,
                    templates=templates,
                    scale=scale,
                    battle_count=battle_count,
                    pollute_count=pollute_count,
                    capture_score=capture_score,
                    pollute_capture_score=pollute_capture_score,
                    window_width=width,
                    window_height=height,
                )

                if battle_start_by_state:
                    self._mode.on_battle_start(event)

                # Tick display
                self._mode.on_tick_display(event, is_hit, action_score, action_template)

                now = time.time()
                cooldown_ready = (now - last_trigger_time) >= CONFIG.trigger_cooldown_sec

                if detected and is_hit and cooldown_ready:
                    extra_cooldown = self._mode.on_action(event, is_hit, action_score)
                    if extra_cooldown is not None:
                        last_trigger_time = now + extra_cooldown
                    else:
                        last_trigger_time = now

                if battle_end_by_state:
                    self._mode.on_battle_end(event)

                in_battle_state = detected
                self._push_status(
                    battle_count=battle_count,
                    pollute_count=pollute_count,
                    state="战斗中" if in_battle_state else "待机",
                    score=action_score,
                )
                time.sleep(interval)
