#!/usr/bin/env python3
"""Офлайн-инвентаризация ./ComfyUI-local/ -> cw_local_catalog.json.

Локальный корень ComfyUI: ./cwbuilder-docs/ComfyUI-local/ с 22 подпапками
(checkpoints, diffusion_model, diffusion_model_gguf, lora, vae, controlnet,
text_encoders, clip, tts, upscale_model, ...). Считает модели по категориям,
пишет каталог. Сеть не используется.

    python parse_inventory.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

CW_ROOT = Path(__file__).resolve().parent
LOCAL = CW_ROOT / "ComfyUI-local"
CATALOG_OUT = CW_ROOT / "cw_local_catalog.json"

# 22 стандартные подпапки ComfyUI models dir
SUBDIRS = [
    "checkpoints", "diffusion_model", "diffusion_model_gguf", "unet_models",
    "lora", "vae", "vae_approx", "controlnet", "clip", "clip_vision",
    "text_encoders", "upscale_model", "ipadapter", "motion_modules",
    "audio_encoders", "tts", "facerestore_models", "detection",
    "background_removal", "frame_interpolation", "style_models", "gligen",
]
MODEL_EXT = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".pkl"}


def scan() -> dict:
    models: list[dict] = []
    for sub in SUBDIRS:
        d = LOCAL / sub
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix.lower() in MODEL_EXT:
                models.append({
                    "name": f.name,
                    "category": sub,
                    "path": str(f.relative_to(LOCAL)).replace("\\", "/"),
                    "size_mb": round(f.stat().st_size / 1e6, 1),
                })
    return {
        "local_root": "./cwbuilder-docs/ComfyUI-local",
        "total_models": len(models),
        "by_category": dict(Counter(m["category"] for m in models)),
        "models": models,
        "custom_nodes_detected": [],
        "workflows": [w.name for w in CW_ROOT.glob("workflow_*.json")],
    }


def main() -> None:
    cat = scan()
    CATALOG_OUT.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] Каталог: {cat['total_models']} моделей -> cw_local_catalog.json")
    for k, v in cat["by_category"].items():
        print(f"     {k}: {v}")


if __name__ == "__main__":
    main()
