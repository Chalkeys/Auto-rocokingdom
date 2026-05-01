"""Scan bag UI for ball counts using OCR + template matching."""
from __future__ import annotations

import os
import re
from typing import Optional

import cv2
import numpy as np

from config import runtime_path

_PATTERN = re.compile(r"[xX×]\s*(\d+)")
_TMPL_DIR = "ball_templates"
_ICON_SIZE = 64
_MATCH_THRESHOLD = 0.75


def templates_dir() -> str:
    return runtime_path(_TMPL_DIR)


def load_ball_templates() -> dict[str, np.ndarray]:
    """Load templates from ball_templates/. Returns {name: gray 64×64}."""
    d = templates_dir()
    if not os.path.isdir(d):
        return {}
    result = {}
    for fname in os.listdir(d):
        if not fname.lower().endswith(".png"):
            continue
        name = os.path.splitext(fname)[0]
        img = cv2.imread(os.path.join(d, fname), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            result[name] = cv2.resize(img, (_ICON_SIZE, _ICON_SIZE))
    return result


def _ocr_frame(bgr: np.ndarray) -> list:
    try:
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(bgr)
        return result or []
    except Exception:
        return []


def _find_count_positions(ocr_results: list) -> list[tuple[float, float, int]]:
    """Return (cy, cx, count) for each 'x<N>' OCR hit."""
    hits = []
    for item in ocr_results:
        try:
            box, text, _ = item
            m = _PATTERN.search(text)
            if not m:
                continue
            pts = np.array(box, dtype=np.float32)
            cx = float(pts[:, 0].mean())
            cy = float(pts[:, 1].mean())
            hits.append((cy, cx, int(m.group(1))))
        except Exception:
            continue
    return hits


def _estimate_icon_height(hits: list[tuple[float, float, int]]) -> float:
    """Estimate icon height from the vertical spacing between grid rows."""
    if len(hits) < 2:
        return 70.0
    ys = sorted({round(cy / 50) * 50 for cy, *_ in hits})
    if len(ys) < 2:
        return 70.0
    gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    return float(min(gaps)) * 0.75


def _crop_icon(bgr: np.ndarray, cx: float, cy: float, icon_h: float) -> Optional[np.ndarray]:
    """Crop the icon above the count text at (cx, cy)."""
    h, w = bgr.shape[:2]
    gap = max(4, int(icon_h * 0.05))
    top = max(0, int(cy - icon_h - gap))
    bot = max(0, int(cy - gap))
    half = int(icon_h / 2)
    left = max(0, int(cx) - half)
    right = min(w, int(cx) + half)
    if bot <= top or right <= left:
        return None
    crop = bgr[top:bot, left:right]
    return crop if crop.size > 0 else None


def _match_icon(icon_bgr: np.ndarray, templates: dict[str, np.ndarray]) -> Optional[str]:
    """Return the best-matching template name, or None if below threshold."""
    if not templates:
        return None
    gray = cv2.cvtColor(icon_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (_ICON_SIZE, _ICON_SIZE))
    best_name, best_score = None, 0.0
    for name, tmpl in templates.items():
        score = float(cv2.matchTemplate(resized, tmpl, cv2.TM_CCOEFF_NORMED).max())
        if score > best_score:
            best_score, best_name = score, name
    return best_name if best_score >= _MATCH_THRESHOLD else None


def extract_icons(hwnd: int) -> list[tuple[np.ndarray, int]]:
    """
    Capture the bag and return (icon_bgr, count) pairs in grid order.
    Used for the template-setup dialog.
    """
    from core.capture import capture_window_bgr
    frame = capture_window_bgr(hwnd)
    if frame is None:
        return []
    hits = _find_count_positions(_ocr_frame(frame))
    if not hits:
        return []
    icon_h = _estimate_icon_height(hits)
    hits.sort(key=lambda h: (round(h[0] / 50), h[1]))
    result = []
    for cy, cx, count in hits:
        crop = _crop_icon(frame, cx, cy, icon_h)
        if crop is not None:
            result.append((crop, count))
    return result


def scan_balls(hwnd: int) -> dict[str, int]:
    """
    Scan the bag screenshot for ball counts.
    Matches icons against stored templates; falls back to positional labels.
    Returns {ball_name: count}.
    """
    from core.capture import capture_window_bgr
    frame = capture_window_bgr(hwnd)
    if frame is None:
        return {}
    hits = _find_count_positions(_ocr_frame(frame))
    if not hits:
        return {}

    icon_h = _estimate_icon_height(hits)
    templates = load_ball_templates()
    hits.sort(key=lambda h: (round(h[0] / 50), h[1]))

    out: dict[str, int] = {}
    name_counts: dict[str, int] = {}
    for i, (cy, cx, count) in enumerate(hits):
        crop = _crop_icon(frame, cx, cy, icon_h)
        name = (_match_icon(crop, templates) if crop is not None and templates else None)
        if name is None:
            name = f"球{i + 1:02d}"
        # Deduplicate if same template matched twice
        n = name_counts.get(name, 0) + 1
        name_counts[name] = n
        out[f"{name}_{n}" if n > 1 else name] = count
    return out


def save_template(name: str, icon_bgr: np.ndarray) -> str:
    """Save an icon crop as a named ball template. Returns the file path."""
    d = templates_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{name}.png")
    cv2.imwrite(path, icon_bgr)
    return path


def diff_balls(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Return {name: consumed} for balls whose count decreased."""
    return {k: before[k] - after.get(k, 0) for k in before if before[k] - after.get(k, 0) > 0}
