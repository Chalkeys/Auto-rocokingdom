import re

import cv2
import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR as _RapidOCR
    _reader = _RapidOCR()
except ImportError:
    _reader = None

from config import CONFIG


def _extract_ocr_roi(full_bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    l = max(0, int(width * CONFIG.ocr_roi_left_ratio))
    t = max(0, int(height * CONFIG.ocr_roi_top_ratio))
    w = max(1, min(width - l, int(width * CONFIG.ocr_roi_width_ratio)))
    h = max(1, min(height - t, int(height * CONFIG.ocr_roi_height_ratio)))
    return full_bgr[t:t + h, l:l + w]


def _preprocess(bgr_patch: np.ndarray) -> np.ndarray:
    scale = CONFIG.ocr_upscale_factor
    new_w = max(1, int(bgr_patch.shape[1] * scale))
    new_h = max(1, int(bgr_patch.shape[0] * scale))
    return cv2.resize(bgr_patch, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def recognize_spirit_name(full_bgr: np.ndarray, width: int, height: int) -> str:
    if _reader is None:
        return CONFIG.ocr_fallback_text
    try:
        patch = _extract_ocr_roi(full_bgr, width, height)
        processed = _preprocess(patch)
        result, _ = _reader(processed)
        if not result:
            return CONFIG.ocr_fallback_text
        first_text = result[0][1]
        match = re.match(r"[一-鿿]+", first_text)
        return match.group(0) if match else CONFIG.ocr_fallback_text
    except Exception:
        return CONFIG.ocr_fallback_text
