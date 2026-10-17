#!/usr/bin/env python3
"""Pipeline генерации видео: локальный ComfyUI :8197 (MiniMax turbo workflows).

    python pipelines/video_pipeline.py --prompt "test" [--workflow minimax_4step]
        [--model minimax_h3_fl2va_pruned_w6a8.safetensors] [--out output/video.mp4]
Разрешение 1024x1024, batch 1, timeout 3600s — из конфига.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import video_gen  # noqa: E402
import config as C  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--workflow", default="minimax_4step",
                    choices=list(C.CW_WORKFLOWS.keys()))
    ap.add_argument("--model", default=C.VIDEO_DEFAULT_MODEL)
    ap.add_argument("--width", type=int, default=C.IMAGE_WIDTH)
    ap.add_argument("--height", type=int, default=C.IMAGE_HEIGHT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-enhance", action="store_true")
    a = ap.parse_args()

    out = Path(a.out or C.OUTPUT_DIR / f"video_{int(time.time())}.mp4")
    print(f"[video] prompt: {a.prompt!r} -> ComfyUI :{C.COMFY_VIDEO_PORT} "
          f"(workflow={a.workflow}, model={a.model}) только localhost")
    p = video_gen.generate(a.prompt, out, workflow=a.workflow, model=a.model,
                           width=a.width, height=a.height, enhance_prompt=not a.no_enhance)
    print(f"ГОТОВО: {p}")


if __name__ == "__main__":
    main()
