import csv
import os
from datetime import datetime

from config import CONFIG, runtime_path


def _log_path() -> str:
    return runtime_path(CONFIG.pollute_log_path)


def _ensure_csv_file() -> None:
    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["序号", "时间", "污染精灵"])


def log_mode_start(mode_label: str) -> None:
    try:
        _ensure_csv_file()
        brief_time = datetime.now().strftime("%m/%d %H:%M")
        with open(_log_path(), "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["#", brief_time, f"mode={mode_label}"])
    except Exception:
        pass


def log_pollute_battle(serial: int, spirit_name: str) -> None:
    try:
        _ensure_csv_file()
        brief_time = datetime.now().strftime("%m/%d %H:%M")
        with open(_log_path(), "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([serial, brief_time, spirit_name])
    except Exception:
        pass
