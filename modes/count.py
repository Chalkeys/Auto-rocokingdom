from typing import Optional

from modes.base import BaseMode, BattleEvent


class CountMode(BaseMode):
    @property
    def name(self) -> str:
        return "count_only"

    @property
    def label(self) -> str:
        return "污染计数模式"

    def on_action(self, event: BattleEvent, is_hit: bool, action_score: float) -> Optional[float]:
        return None
