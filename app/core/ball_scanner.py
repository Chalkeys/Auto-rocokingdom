"""Scan the game window for ball counts shown as 'x<N>' in the bag UI."""
from __future__ import annotations

import re
from typing import Optional

import cv2
import numpy as np

_PATTERN = re.compile(r"[xX×]\s*(\d+)")


def _ocr_frame(bgr) -> list[tuple[str, tuple, float]]:
    """Run RapidOCR on a BGR frame; returns list of (text, box, score)."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        reader = RapidOCR()
        result, _ = reader(bgr)
        if not result:
            return []
        return result  # each item: (box, text, score)
    except Exception:
        return []


def scan_balls(hwnd: int) -> dict[str, int]:
    """
    Capture the game window and extract all 'x<N>' counts from the bag UI.
    Returns an ordered dict keyed by grid position label ('球01', '球02', …).
    """
    from core.capture import capture_window_bgr
    frame = capture_window_bgr(hwnd)
    if frame is None:
        return {}

    results = _ocr_frame(frame)
    hits: list[tuple[float, float, int]] = []  # (cx, cy, count)

    for item in results:
        try:
            box, text, _score = item
            m = _PATTERN.search(text)
            if not m:
                continue
            count = int(m.group(1))
            pts = np.array(box, dtype=np.float32)
            cx = float(pts[:, 0].mean())
            cy = float(pts[:, 1].mean())
            hits.append((cy, cx, count))
        except Exception:
            continue

    # Sort top-to-bottom, left-to-right (group rows by 60px bands)
    hits.sort(key=lambda h: (round(h[0] / 60), h[1]))

    return {f"球{i+1:02d}": count for i, (_cy, _cx, count) in enumerate(hits)}


def diff_balls(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Return {label: consumed} for balls that decreased. Ignores new or increased entries."""
    result = {}
    for key, before_count in before.items():
        after_count = after.get(key, 0)
        used = before_count - after_count
        if used > 0:
            result[key] = used
    return result
