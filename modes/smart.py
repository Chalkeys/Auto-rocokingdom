import logging
from typing import Optional

from config import CONFIG
from core.input import press_once
from core.logger import log_audit
from modes.base import BaseMode, BattleEvent
from modes.escape import EscapeMode

ACTION_OPTIONS = {
    "1": ("gather", "只聚能（按 X）"),
    "2": ("escape", "逃跑（按 ESC + 确认）"),
    "3": ("skill1_gather", "释放技能1后聚能（按 1，再按 X）"),
}


class SmartMode(BaseMode):
    def __init__(self, pollute_action: str = "gather", normal_action: str = "escape") -> None:
        self._escape_delegate = EscapeMode()
        self._pollute_action = pollute_action
        self._normal_action = normal_action
        self._current_action: Optional[str] = None
        self._skill1_used = False

    @property
    def name(self) -> str:
        return "smart"

    @property
    def label(self) -> str:
        return "智能模式"

    def _classify(self, event: BattleEvent) -> str:
        if event.pollute_capture_score > event.capture_score:
            return "pollute"
        return "normal"

    def _action_label(self, action: str) -> str:
        labels = {"gather": "聚能", "escape": "逃跑", "skill1_gather": "技能1+聚能"}
        return labels.get(action, action)

    def on_battle_start(self, event: BattleEvent) -> None:
        battle_type = self._classify(event)
        self._current_action = (
            self._pollute_action if battle_type == "pollute" else self._normal_action
        )
        self._skill1_used = False

        mode_label = "污染" if battle_type == "pollute" else "普通"
        action_label = self._action_label(self._current_action)
        logging.info(
            "智能模式判型: 本场=%s → %s（capture=%.3f, pollute_capture=%.3f）",
            mode_label, action_label,
            event.capture_score, event.pollute_capture_score,
        )
        log_audit(
            "智能模式判型",
            战斗次数=event.battle_count,
            战斗类型=mode_label,
            动作=self._current_action,
            capture分数=round(event.capture_score, 4),
            pollute_capture分数=round(event.pollute_capture_score, 4),
        )

    def on_action(self, event: BattleEvent, is_hit: bool, action_score: float) -> Optional[float]:
        if not is_hit:
            return None

        if self._current_action is None:
            battle_type = self._classify(event)
            self._current_action = (
                self._pollute_action if battle_type == "pollute" else self._normal_action
            )
            self._skill1_used = False
            logging.info("智能模式兜底判型: %s → %s", battle_type, self._action_label(self._current_action))

        if self._current_action == "gather":
            press_once(event.hwnd, CONFIG.press_key)
            logging.info("智能模式动作: 已触发按键 %s（本场=聚能）", CONFIG.press_key)
            return None
        elif self._current_action == "escape":
            logging.info("智能模式动作: 已触发 ESC（本场=逃跑）")
            return self._escape_delegate.on_action(event, is_hit, action_score)
        elif self._current_action == "skill1_gather":
            if not self._skill1_used:
                press_once(event.hwnd, "1")
                self._skill1_used = True
                logging.info("智能模式动作: 已释放技能1（本场=技能1+聚能）")
                return 1.0
            else:
                press_once(event.hwnd, CONFIG.press_key)
                logging.info("智能模式动作: 已触发按键 %s（本场=技能1+聚能）", CONFIG.press_key)
                return None
        return None

    def on_battle_end(self, event: BattleEvent) -> None:
        self._current_action = None
        self._skill1_used = False

    def on_tick_display(self, event: BattleEvent, is_hit: bool, action_score: float, action_template: str) -> None:
        logging.info(
            "行动检测=%s 行动分数=%.3f 检测模板=%s 污染次数=%d",
            is_hit, action_score, action_template, event.pollute_count,
        )
