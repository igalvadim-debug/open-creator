#!/usr/bin/env python3
"""Pipeline генерации изображений: локальный ComfyUI :8291 + энханс через LLM :8484.

    python pipelines/image_pipeline.py --prompt "test" [--out output/img.png]
                                        [--width 1024] [--height 1024] [--no-enhance]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import image_gen  # noqa: E402
import config as C  # noqa: E402


def main() -> None:
    """Generate an image from CLI options and write it to the requested path
    or a timestamped default. Generation errors propagate."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--width", type=int, default=C.IMAGE_WIDTH)
    ap.add_argument("--height", type=int, default=C.IMAGE_HEIGHT)
    ap.add_argument("--no-enhance", action="store_true")
    a = ap.parse_args()

    out = Path(a.out or C.OUTPUT_DIR / f"image_{int(time.time())}.png")
    print(f"[image] prompt: {a.prompt!r} -> ComfyUI :{C.COMFY_IMAGE_PORT} (только localhost)")
    p = image_gen.generate(a.prompt, out, enhance_prompt=not a.no_enhance,
                           width=a.width, height=a.height)
    print(f"ГОТОВО: {p}")


if __name__ == "__main__":
    main()
