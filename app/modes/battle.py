import logging
from typing import Optional

from config import CONFIG
from core.input import press_once
from modes.base import BaseMode, BattleEvent


class BattleMode(BaseMode):
    @property
    def name(self) -> str:
        return "battle"

    @property
    def label(self) -> str:
        return "聚能模式"

    def on_action(self, event: BattleEvent, is_hit: bool, action_score: float) -> Optional[float]:
        if not is_hit:
            return None
        press_once(event.hwnd, CONFIG.press_key)
        logging.info("已触发按键: %s（聚能模式）", CONFIG.press_key)
        return None
