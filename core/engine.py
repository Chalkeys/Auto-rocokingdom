import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import mss

from config import CONFIG
from core.capture import capture_window_bgr
from core.input import press_once
from core.logger import log_audit
from core.vision import (
    Template,
    best_match_score,
    load_templates,
    normalize_poll_interval,
    normalize_template_name,
    preprocess,
    match_single,
)

# Templates excluded from action detection scoring
_ACTION_SPECIAL_KEYS = {"yes.png", "qiudaidai.png"}

from core.window import find_window_by_keyword, get_client_rect_on_screen, find_all_windows_by_keyword
from modes.base import BaseMode, BattleEvent


_SEP = "══════════════════════════════════════════════════════════"

# Map each battle-end template to its ROI region (left_ratio, top_ratio, w_ratio, h_ratio)
_BATTLE_END_ROI = {
    "elf_p.png": (0.5, 0.0, 0.5, 0.5),
    "missions.png": (0.5, 0.0, 0.5, 0.5),
    "heaths.png": (0.0, 0.0, 0.5, 0.5),
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
    ) -> None:
        self._mode = mode
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._status_callback = status_callback
        self._target_hwnd = target_hwnd

    def _push_status(self, **kwargs: object) -> None:
        if self._status_callback is not None:
            self._status_callback(kwargs)

    def run(self) -> None:
        logging.info("检测器已启动，按 Ctrl+C 退出。")
        logging.info("本脚本仅用于授权测试。")

        templates = load_templates()
        interval = normalize_poll_interval(CONFIG.poll_interval_sec)
        capture_template_key = normalize_template_name(CONFIG.capture_template_name)
        pollute_capture_template_key = normalize_template_name(CONFIG.pollute_capture_template_name)
        reconnect_template_key = normalize_template_name(CONFIG.reconnect_template_name)
        loaded_template_keys = {normalize_template_name(t.name) for t in templates}

        # Normalize battle-end template names
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
                logging.warning(
                    "智能模式缺少普通战斗模板: 配置=%s",
                    CONFIG.capture_template_name,
                )
            if pollute_capture_template_key not in loaded_template_keys:
                logging.warning(
                    "智能模式缺少污染战斗模板: 配置=%s",
                    CONFIG.pollute_capture_template_name,
                )

        in_battle = False
        last_trigger_time = 0.0
        battle_count = 0
        pollute_count = 0

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

                # Extract per-template scores from main ROI
                capture_score = next(
                    (s for n, s in all_matches if normalize_template_name(n) == capture_template_key),
                    0.0,
                )
                pollute_capture_score = next(
                    (s for n, s in all_matches if normalize_template_name(n) == pollute_capture_template_key),
                    0.0,
                )

                # ── Battle-end detection across multiple ROIs ──
                roi_cache: Dict[tuple, object] = {}
                end_scores: List[Tuple[str, float]] = []
                for key, roi_params in battle_end_keys.items():
                    cache_key = roi_params
                    if cache_key not in roi_cache:
                        roi_bgr = _extract_roi(full_window_bgr, width, height, *roi_params)
                        roi_cache[cache_key] = preprocess(roi_bgr)
                    roi_processed = roi_cache[cache_key]
                    s = match_single(roi_processed, templates, key, scale=scale)
                    end_scores.append((key, s))

                best_end_score = max((s for _, s in end_scores), default=0.0)
                best_end_name = max(end_scores, key=lambda x: x[1])[0] if end_scores else ""

                # Action score: exclude battle-end, qiudaidai, yes
                excluded_keys = set(battle_end_keys.keys()) | _ACTION_SPECIAL_KEYS
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

                # ── Battle start: action detected in non-battle state ──
                if not in_battle and is_hit:
                    battle_count += 1
                    is_pollute_battle = pollute_capture_score > capture_score
                    if is_pollute_battle:
                        pollute_count += 1

                    logging.info(_SEP)
                    logging.info(
                        ">>> 检测到战斗开始（第 %d 场，%s，累计污染 %d 次）",
                        battle_count,
                        "污染" if is_pollute_battle else "普通",
                        pollute_count,
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

                    log_audit(
                        "战斗次数增加",
                        战斗次数=battle_count,
                        污染次数=pollute_count,
                    )
                    in_battle = True

                # ── Battle end: best battle-end template ──
                end_detected = best_end_score >= CONFIG.match_threshold
                if in_battle and end_detected:
                    logging.info("<<< 检测到战斗结束（第 %d 场，%.3f by %s）", battle_count, best_end_score, best_end_name)
                    logging.info(_SEP)

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

                    # ── Teammate reconnect detection (silent) ──
                    center_roi = CONFIG.reconnect_center_roi
                    center_bgr = _extract_roi(full_window_bgr, width, height, *center_roi)
                    center_processed = preprocess(center_bgr)
                    reconnect_score = match_single(center_processed, templates, reconnect_template_key, scale=scale)

                    if reconnect_score >= CONFIG.match_threshold:
                        logging.debug("检测到同行请求，按 F 确认（qiudaidai=%.3f）", reconnect_score)
                        press_once(hwnd, CONFIG.reconnect_accept_key)

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
                # on_tick_display handled above in per-tick display block

                # ── Action within battle ──
                now = time.time()
                cooldown_ready = (now - last_trigger_time) >= CONFIG.trigger_cooldown_sec

                if in_battle and is_hit and cooldown_ready:
                    extra_cooldown = self._mode.on_action(event, is_hit, action_score)
                    if extra_cooldown is not None:
                        last_trigger_time = now + extra_cooldown
                    else:
                        last_trigger_time = now

                self._push_status(
                    battle_count=battle_count,
                    pollute_count=pollute_count,
                    state="战斗中" if in_battle else "待机",
                    score=action_score,
                )
                time.sleep(interval)
