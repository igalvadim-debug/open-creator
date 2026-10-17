#!/usr/bin/env python3
"""cw_local.py — локальный CLI-хелпер офлайн-каталога ComfyUI.

    python cw_local.py layout   # показать структуру ./ComfyUI-local (22 папки)
    python cw_local.py setup    # создать структуру папок + базовый каталог
    python cw_local.py find <имя|категория>  # поиск модели в каталоге
    python cw_local.py catalog  # сводка каталога
Только локальные пути; внешних обращений нет.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL = HERE / "ComfyUI-local"
CATALOG = HERE / "cw_local_catalog.json"

SUBDIRS = [
    "checkpoints", "diffusion_model", "diffusion_model_gguf", "unet_models",
    "lora", "vae", "vae_approx", "controlnet", "clip", "clip_vision",
    "text_encoders", "upscale_model", "ipadapter", "motion_modules",
    "audio_encoders", "tts", "facerestore_models", "detection",
    "background_removal", "frame_interpolation", "style_models", "gligen",
]


def cmd_layout() -> None:
    """Print each model directory status and recursive entry count."""
    print(f"Корень: ./{LOCAL.relative_to(HERE.parent)}")
    for s in SUBDIRS:
        d = LOCAL / s
        n = len(list(d.rglob("*"))) if d.is_dir() else 0
        mark = "OK " if d.is_dir() else "-- "
        print(f"  [{mark}] {s:<24} ({n} файлов)")


def cmd_setup() -> None:
    """Create model directories and an empty catalog if one does not exist."""
    for s in SUBDIRS:
        (LOCAL / s).mkdir(parents=True, exist_ok=True)
    print(f"[ok] Создано {len(SUBDIRS)} подпапок в ./{LOCAL.relative_to(HERE.parent)}")
    if not CATALOG.exists():
        CATALOG.write_text(json.dumps({"local_root": "./cwbuilder-docs/ComfyUI-local",
                                       "total_models": 0, "models": []}, indent=2),
                           encoding="utf-8")
        print("[ok] Базовый cw_local_catalog.json создан. Заполните модели и запустите "
              "python parse_inventory.py")


def load_catalog() -> dict:
    """Load the JSON catalog; exit with a message if it is missing.

    Read and JSON decoding errors propagate."""
    if not CATALOG.exists():
        sys.exit("Нет cw_local_catalog.json — запустите python parse_inventory.py")
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def cmd_find(q: str) -> None:
    """Print up to 50 case-insensitive name substring or exact category matches
    and the total match count. Catalog loading errors propagate."""
    cat = load_catalog()
    ql = q.lower()
    hits = [m for m in cat.get("models", [])
            if ql in m["name"].lower() or ql == m["category"].lower()]
    for m in hits[:50]:
        print(f"  {m['category']:<22} {m['name']}  ({m.get('size_mb', '?')} MB)")
    print(f"[{len(hits)} совпадений]")


def cmd_catalog() -> None:
    """Print catalog totals, category counts, and workflow names."""
    cat = load_catalog()
    print(f"Моделей всего: {cat.get('total_models', len(cat.get('models', [])))}")
    for k, v in (cat.get("by_category") or {}).items():
        print(f"  {k}: {v}")
    print("Workflow:", ", ".join(cat.get("workflows", [])) or "-")


def main() -> None:
    """Dispatch the catalog CLI command, or print help for no/unknown command."""
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "layout":
        cmd_layout()
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "find":
        cmd_find(args[1] if len(args) > 1 else "")
    elif cmd == "catalog":
        cmd_catalog()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
