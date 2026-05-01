"""Session state persistence — survives unexpected exits."""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from config import runtime_path

_SESSION_FILE = "logs/session.json"


def _path() -> str:
    return runtime_path(_SESSION_FILE)


def save(
    *,
    battle_count: int,
    pollute_count: int,
    mode_label: str,
    start_time: float,
    clean_exit: bool = False,
    is_paused: bool = False,
    ball_start: Optional[dict] = None,
) -> None:
    try:
        p = _path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "battle_count": battle_count,
                "pollute_count": pollute_count,
                "mode_label": mode_label,
                "start_time": start_time,
                "save_time": time.time(),
                "clean_exit": clean_exit,
                "is_paused": is_paused,
                "ball_start": ball_start or {},
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load() -> Optional[dict]:
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def mark_clean() -> None:
    """Mark current session as cleanly exited."""
    data = load()
    if data:
        data["clean_exit"] = True
        try:
            with open(_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def clear() -> None:
    try:
        os.remove(_path())
    except Exception:
        pass
