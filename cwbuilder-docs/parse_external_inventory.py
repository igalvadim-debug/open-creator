#!/usr/bin/env python3
"""parse_external_inventory.py — импорт внешнего инвентаря моделей ComfyUI.

Формат строк (CSV, как в выводе сканера):
    C:\\ai_diffusion\\models\\loras\\foo.safetensors  →  Trigger: bar / baz
    D:\\ComfyUiCuda\\models\\vae\\x.safetensors            (без триггера)

Пути Windows (C:/D:) НЕ копируются и НЕ становятся рантайм-путями проекта:
они нормализуются в относительные имена вида "<root>/models/<category>/file"
и сопоставляются с локальным корнем ./ComfyUI-local/. Реальные веса пользователь
переносит/скачивает сам при установке (сеть только на этапе установки).

Использование:
    python parse_external_inventory.py inventory.csv          # dry-run: сводка
    python parse_external_inventory.py inventory.csv --apply  # добавить записи в cw_local_catalog.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

CW_ROOT = Path(__file__).resolve().parent
CATALOG = CW_ROOT / "cw_local_catalog.json"
LOCAL = CW_ROOT / "ComfyUI-local"

LINE_RE = re.compile(
    r"^\s*(?P<path>[A-Za-z]:[\\/][^\t\n]*?)\s*"
    r"(?:→|->|=>)\s*Trigger:\s*(?P<trig>.+?)\s*$",
    re.IGNORECASE,
)
PLAIN_RE = re.compile(r"^\s*(?P<path>[A-Za-z]:[\\/][^\t\n]*?)\s*$")

MODEL_EXT = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".pkl"}

# Маппинг папок источника -> категория каталога (22 подпапки cw_local)
CATEGORY_MAP = {
    "checkpoints": "checkpoints",
    "diffusion_models": "diffusion_model",
    "unet": "unet_models",
    "loras": "lora",
    "vae": "vae",
    "vae_approx": "vae_approx",
    "controlnet": "controlnet",
    "ControlNetModel": "controlnet",
    "clip_vision": "clip_vision",
    "text_encoders": "text_encoders",
    "text_enchancer": "text_encoders",
    "LLM": "text_encoders",
    "upscale_models": "upscale_model",
    "latent_upscale_models": "upscale_model",
    "ipadapter": "ipadapter",
    "audio_encoders": "audio_encoders",
    "wav2vec2": "audio_encoders",
    "qwen-tts": "tts",
    "facerestore_models": "facerestore_models",
    "ultralytics": "detection",
    "sam2": "detection",
    "sam3": "detection",
    "sams": "detection",
    "grounding-dino": "detection",
    "florence2": "detection",
    "face_parsing": "detection",
    "segformer_b2_clothes": "detection",
    "rembg": "background_removal",
    "RMBG": "background_removal",
    "vitmatte": "background_removal",
    "frame_interpolation": "frame_interpolation",
    "style_models": "style_models",
    "embeddings": "gligen",
    "inpaint": "diffusion_model",
    "clipseg": "clip",
    "model_patches": "diffusion_model",
    "SEEDVR2": "diffusion_model",
    "transformers": "diffusion_model",
    "xlabs": "controlnet",
    "liveportrait": "motion_modules",
}


def category_from_path(path: str) -> str:
    parts = re.split(r"[\\/]", path)
    try:
        mi = parts.index("models")
    except ValueError:
        return "misc"
    rest = parts[mi + 1:-1]  # папки после models/, без файла
    for p in rest:
        if p in CATEGORY_MAP:
            return CATEGORY_MAP[p]
    return rest[0].lower() if rest else "misc"


def rel_name(path: str) -> str:
    """Относительное имя внутри ComfyUI-local (без диска, только 'models/' и далее)."""
    parts = re.split(r"[\\/]", path)
    if "models" in parts:
        idx = parts.index("models")
        return "/".join(parts[idx + 1:])
    return "/".join(parts[-2:])


def parse_line(line: str) -> tuple[str, str] | None:
    m = LINE_RE.match(line)
    if m:
        trig = m.group("trig").strip()
        if trig in {"–", "-", "(kein Trigger)", "null"} or trig.lower().startswith("(kein"):
            trig = ""
        return m.group("path"), trig
    m = PLAIN_RE.match(line)
    if m and not line.strip().endswith("/") and " " not in m.group("path").strip():
        return m.group("path").strip(), ""
    return None


def load_entries(text: str) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        parsed = parse_line(line)
        if not parsed:
            continue
        path, trig = parsed
        name = re.split(r"[\\/]", path)[-1]
        if Path(name).suffix.lower() not in MODEL_EXT:
            continue
        cat = category_from_path(path)
        rn = rel_name(path)
        key = f"{cat}/{rn}"
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "name": name,
            "category": cat,
            "path": rn,
            "size_mb": 0.0,           # неизвестен из текстового инвентаря
            "trigger": trig,
            "source_root": re.split(r"[\\/]", path)[0],  # "C:" / "D:"
            "present": False,          # файл ещё не перенесён в ./ComfyUI-local
        })
    return entries


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit(__doc__)
    src = Path(argv[1])
    apply = "--apply" in argv
    entries = load_entries(src.read_text(encoding="utf-8"))

    by_cat = Counter(e["category"] for e in entries)
    print(f"[scan] Записей: {len(entries)}")
    for k, v in sorted(by_cat.items()):
        print(f"       {k:<24} {v}")
    no_trig = sum(1 for e in entries if e["trigger"])
    print(f"[scan] С триггерами: {no_trig}")

    if not apply:
        print("[dry-run] Без изменений каталога. Добавьте --apply.")
        return

    cat = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else \
        {"local_root": "./cwbuilder-docs/ComfyUI-local", "total_models": 0, "models": []}
    existing = {(m["category"], m["path"]) for m in cat.get("models", [])}
    added = 0
    for e in entries:
        if (e["category"], e["path"]) not in existing:
            cat["models"].append(e)
            added += 1
    # обновить present-флаги по факту файлов в ./ComfyUI-local
    for m in cat["models"]:
        if LOCAL.is_dir():
            m["present"] = (LOCAL / m["path"]).exists()
    cat["total_models"] = len(cat["models"])
    cat["by_category"] = dict(Counter(m["category"] for m in cat["models"]))
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] Добавлено {added} записей -> cw_local_catalog.json "
          f"(всего {cat['total_models']})")


if __name__ == "__main__":
    main(sys.argv)
