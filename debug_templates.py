import glob
import os

import cv2

from config import CONFIG
from core.vision import preprocess


def main():
    pattern = os.path.join(CONFIG.template_dir, CONFIG.template_pattern)
    paths = sorted(glob.glob(pattern))
    os.makedirs("template_debug", exist_ok=True)

    for path in paths:
        raw = cv2.imread(path)
        if raw is None:
            continue
        name = os.path.basename(path)
        if "yes" in name.lower() or "qiudaidai" in name.lower():
            processed = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        else:
            processed = preprocess(raw)
        cv2.imwrite(os.path.join("template_debug", name), processed)
        print(f"已输出: template_debug/{name}")

        if "qiudaidai" in name.lower():
            hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
            _, saturation, _ = cv2.split(hsv)
            _, mask = cv2.threshold(saturation, 40, 255, cv2.THRESH_BINARY)
            cv2.imwrite(os.path.join("template_debug", f"mask_{name}"), mask)
            print(f"已输出: template_debug/mask_{name}")


if __name__ == "__main__":
    main()
