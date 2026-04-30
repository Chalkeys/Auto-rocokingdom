import logging
import random
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import mss

from config import CONFIG
from core.capture import capture_window_bgr
from core.input import press_once
from core.ocr import recognize_spirit_name
from core.pollute_logger import log_mode_start, log_pollute_battle
from core.vision import (
    Template,
    best_match_score,
    load_templates,
    normalize_poll_interval,
    normalize_template_name,
    preprocess,
    match_single,
)

_ACTION_EXCLUDE_KEYS = {
    "yes.png",
    "qiudaidai.png",
    "capture.png",
    "pollute_capture.png",
}

from core.window import find_window_by_keyword, get_client_rect_on_screen, find_all_windows_by_keyword
from modes.base import BaseMode, BattleEvent


_SEP = "══════════════════════════════════════════════════════════"

_NO_WINDOW_TIMEOUT = 20

_BATTLE_END_ROI = {
    "elf_p.png": (0.5, 0.0, 0.5, 0.5),
    "missions.png": (0.5, 0.0, 0.5, 0.5),
    "map.png": (0.5, 0.0, 0.5, 0.5),
}


def _extract_roi(full_bgr, width: int, height: int, left_r: float, top_r: float, w_r: float, h_r: float):
    l = max(0, int(width * left_r))
    t = max(0, int(height * top_r))
    w = max(1, min(width - l, int(width * w_r)))
    h = max(1, min(height - t, int(height * h_r)))
    return full_bgr[t:t + h, l:l + w]


class Engine:
    def __init__(
        self,
        mode: BaseMode,
        stop_event: Optional[threading.Event] = None,
        status_callback: Optional[Callable[[Dict], None]] = None,
        target_hwnd: Optional[int] = None,
        initial_battle_count: int = 0,
        initial_pollute_count: int = 0,
    ) -> None:
        self._mode = mode
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._status_callback = status_callback
        self._target_hwnd = target_hwnd
        self._initial_battle_count = initial_battle_count
        self._initial_pollute_count = initial_pollute_count

    def _push_status(self, **kwargs: object) -> None:
        if self._status_callback is not None:
            self._status_callback(kwargs)

    def run(self) -> None:
        logging.info("检测器已启动（模式: %s）", self._mode.label)
        log_mode_start(self._mode.label)

        templates = load_templates()
        interval = normalize_poll_interval(CONFIG.poll_interval_sec)
        capture_template_key = normalize_template_name(CONFIG.capture_template_name)
        pollute_capture_template_key = normalize_template_name(CONFIG.pollute_capture_template_name)
        reconnect_template_key = normalize_template_name(CONFIG.reconnect_template_name)
        loaded_template_keys = {normalize_template_name(t.name) for t in templates}

        battle_end_keys = {}
        for raw_name in CONFIG.battle_end_template_names:
            key = normalize_template_name(raw_name)
            roi = _BATTLE_END_ROI.get(key, (0.5, 0.0, 0.5, 0.5))
            battle_end_keys[key] = roi
            if key not in loaded_template_keys:
                logging.warning("战斗结束模板未加载: %s", raw_name)
            else:
                logging.info("战斗结束模板已加载: %s → ROI %s", raw_name, roi)

        if self._mode.name == "smart":
            if capture_template_key not in loaded_template_keys:
                logging.warning("智能模式缺少普通战斗模板: 配置=%s", CONFIG.capture_template_name)
            if pollute_capture_template_key not in loaded_template_keys:
                logging.warning("智能模式缺少污染战斗模板: 配置=%s", CONFIG.pollute_capture_template_name)

        in_battle = False
        last_trigger_time = 0.0
        battle_count = self._initial_battle_count
        pollute_count = self._initial_pollute_count
        consecutive_no_window = 0

        try:
            import win32gui as _win32gui
        except ImportError:
            _win32gui = None

        with mss.mss() as sct:
            while not self._stop_event.is_set():
                if self._target_hwnd is not None:
                    hwnd = self._target_hwnd if (_win32gui and _win32gui.IsWindow(self._target_hwnd)) else None
                else:
                    hwnd = find_window_by_keyword(CONFIG.window_title_keyword)
                if hwnd is None:
                    consecutive_no_window += 1
                    if consecutive_no_window >= _NO_WINDOW_TIMEOUT:
                        logging.warning("连续 %d 次未找到游戏窗口，停止运行", _NO_WINDOW_TIMEOUT)
                        self._push_status(state="窗口已丢失", window_lost=True)
                        break
                    logging.warning(
                        "未找到游戏窗口: %s（%d/%d）",
                        CONFIG.window_title_keyword, consecutive_no_window, _NO_WINDOW_TIMEOUT,
                    )
                    self._push_status(state=f"未找到游戏窗口（{consecutive_no_window}/{_NO_WINDOW_TIMEOUT}）")
                    time.sleep(interval)
                    continue
                consecutive_no_window = 0

                left, top, width, height = get_client_rect_on_screen(hwnd)
                if width <= 0 or height <= 0:
                    logging.warning("窗口尺寸无效: %sx%s", width, height)
                    time.sleep(interval)
                    continue

                scale = width / CONFIG.ref_width
                if abs(scale - 1.0) > 0.05:
                    logging.debug("模板缩放系数: %.2f（窗口宽度=%d）", scale, width)

                full_window_bgr = capture_window_bgr(hwnd)

                roi_left = max(0, min(width - 1, int(width * CONFIG.roi_left_ratio)))
                roi_top = max(0, min(height - 1, int(height * CONFIG.roi_top_ratio)))
                roi_w = max(1, min(width - roi_left, int(width * CONFIG.roi_width_ratio)))
                roi_h = max(1, min(height - roi_top, int(height * CONFIG.roi_height_ratio)))

                frame_bgr = full_window_bgr[roi_top:roi_top + roi_h, roi_left:roi_left + roi_w]
                frame_processed = preprocess(frame_bgr)

                score, name, center_loc, all_matches = best_match_score(frame_processed, templates, scale=scale)

                capture_score = next(
                    (s for n, s in all_matches if normalize_template_name(n) == capture_template_key), 0.0,
                )
                pollute_capture_score = next(
                    (s for n, s in all_matches if normalize_template_name(n) == pollute_capture_template_key), 0.0,
                )

                # ── Battle-end detection ──
                roi_cache: Dict[tuple, object] = {}
                end_scores: List[Tuple[str, float]] = []
                for key, roi_params in battle_end_keys.items():
                    if roi_params not in roi_cache:
                        roi_bgr = _extract_roi(full_window_bgr, width, height, *roi_params)
                        roi_cache[roi_params] = preprocess(roi_bgr)
                    s = match_single(roi_cache[roi_params], templates, key, scale=scale)
                    end_scores.append((key, s))

                best_end_score = max((s for _, s in end_scores), default=0.0)
                best_end_name = max(end_scores, key=lambda x: x[1])[0] if end_scores else ""

                # Action score: exclude battle-end templates + special keys
                excluded_keys = set(battle_end_keys.keys()) | _ACTION_EXCLUDE_KEYS
                action_score = -1.0
                action_template = ""
                for tpl_name, tpl_score in all_matches:
                    tpl_key = normalize_template_name(tpl_name)
                    if tpl_key in excluded_keys:
                        continue
                    if tpl_score > action_score:
                        action_score = tpl_score
                        action_template = tpl_name

                is_hit = action_score >= CONFIG.match_threshold

                # ── Battle start ──
                if not in_battle and is_hit:
                    battle_count += 1
                    is_pollute_battle = pollute_capture_score > capture_score
                    spirit_name = ""
                    if is_pollute_battle:
                        pollute_count += 1
                        spirit_name = recognize_spirit_name(full_window_bgr, width, height)
                        log_pollute_battle(pollute_count, spirit_name)

                    logging.info(_SEP)
                    logging.info(
                        ">>> 战斗开始（第 %d 场，%s，累计污染 %d 次%s）"
                        "  [capture=%.3f pollute=%.3f]",
                        battle_count,
                        "污染" if is_pollute_battle else "普通",
                        pollute_count,
                        f"，精灵：{spirit_name}" if spirit_name else "",
                        capture_score,
                        pollute_capture_score,
                    )

                    event = BattleEvent(
                        hwnd=hwnd, templates=templates, scale=scale,
                        battle_count=battle_count, pollute_count=pollute_count,
                        capture_score=capture_score, pollute_capture_score=pollute_capture_score,
                        window_width=width, window_height=height,
                    )
                    self._mode.on_battle_start(event)
                    in_battle = True

                # ── Battle end ──
                end_detected = best_end_score >= CONFIG.match_threshold
                if in_battle and end_detected:
                    logging.info("<<< 战斗结束（第 %d 场，%.3f by %s）", battle_count, best_end_score, best_end_name)
                    logging.info(_SEP)

                    event = BattleEvent(
                        hwnd=hwnd, templates=templates, scale=scale,
                        battle_count=battle_count, pollute_count=pollute_count,
                        capture_score=capture_score, pollute_capture_score=pollute_capture_score,
                        window_width=width, window_height=height,
                    )
                    self._mode.on_battle_end(event)
                    in_battle = False

                # ── Per-tick display ──
                if in_battle:
                    logging.info(
                        "行动检测: %s=%.3f  结束检测: %s=%.3f%s",
                        action_template, action_score,
                        best_end_name, best_end_score,
                        " ← 触发" if end_detected else "",
                    )
                else:
                    logging.info("行动检测: %s=%.3f", action_template, action_score)

                    # ── Teammate reconnect ──
                    center_roi = CONFIG.reconnect_center_roi
                    center_bgr = _extract_roi(full_window_bgr, width, height, *center_roi)
                    center_processed = preprocess(center_bgr)
                    reconnect_score = match_single(center_processed, templates, reconnect_template_key, scale=scale)
                    if reconnect_score >= CONFIG.reconnect_threshold:
                        logging.info("检测到同行请求，按 F 确认（qiudaidai=%.3f）", reconnect_score)
                        press_once(hwnd, CONFIG.reconnect_accept_key)

                event = BattleEvent(
                    hwnd=hwnd, templates=templates, scale=scale,
                    battle_count=battle_count, pollute_count=pollute_count,
                    capture_score=capture_score, pollute_capture_score=pollute_capture_score,
                    window_width=width, window_height=height,
                )

                # ── Action within battle ──
                now = time.time()
                if in_battle and is_hit and (now - last_trigger_time) >= CONFIG.trigger_cooldown_sec:
                    extra_cooldown = self._mode.on_action(event, is_hit, action_score)
                    last_trigger_time = now + (extra_cooldown if extra_cooldown is not None else 0)

                self._push_status(
                    battle_count=battle_count,
                    pollute_count=pollute_count,
                    state="战斗中" if in_battle else "待机",
                    score=action_score,
                )

                jitter = random.uniform(-interval * 0.15, interval * 0.15)
                time.sleep(max(0.05, interval + jitter))
