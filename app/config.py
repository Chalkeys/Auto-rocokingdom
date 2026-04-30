import os
import sys
from dataclasses import dataclass

# app/ directory and the project root (one level up)
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_APP_DIR)


def resource_path(relative: str) -> str:
    """Read-only bundled assets (e.g. templates/). In frozen mode uses _MEIPASS."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(_ROOT, relative)


def runtime_path(relative: str) -> str:
    """Writable runtime files (e.g. logs/). Sibling of the EXE in frozen mode."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(os.path.dirname(sys.executable), relative)
    return os.path.join(_ROOT, relative)


@dataclass(frozen=True)
class AppConfig:
    window_title_keyword: str = "洛克王国：世界"

    ref_width: int = 2560
    ref_height: int = 1600
    require_exact_resolution: bool = False

    poll_interval_sec: float = 2.0

    press_key: str = "x"
    trigger_cooldown_sec: float = 1.0

    escape_click_method: str = "physical"

    match_threshold: float = 0.40
    required_hits: int = 1
    release_misses: int = 2
    use_edge_match: bool = True

    roi_left_ratio: float = 0.5
    roi_top_ratio: float = 0.5
    roi_width_ratio: float = 0.5
    roi_height_ratio: float = 0.5

    template_dir: str = "templates"
    template_pattern: str = "*.png"
    capture_template_name: str = "capture.png"
    pollute_capture_template_name: str = "pollute_capture.png"
    battle_end_template_names: tuple = ("elf_P.png", "missions.png", "map.png")

    reconnect_template_name: str = "qiudaidai.png"
    reconnect_accept_key: str = "f"
    reconnect_center_roi: tuple = (0.25, 0.25, 0.5, 0.5)
    reconnect_threshold: float = 0.6

    # OCR spirit name detection ROI (top-right corner of the game window).
    ocr_roi_left_ratio: float = 0.85
    ocr_roi_top_ratio: float = 0.0
    ocr_roi_width_ratio: float = 0.15
    ocr_roi_height_ratio: float = 0.15
    ocr_upscale_factor: float = 2.0
    ocr_fallback_text: str = "未知"

    pollute_log_path: str = "logs/pollute_log.csv"


CONFIG = AppConfig()
