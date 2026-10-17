#!/usr/bin/env python3
"""Локальный промпт-энхансер: короткий запрос -> детальный промпт.

Использует ЛОКАЛЬНЫЙ llama-server :8484 (OpenAI-совместимый /v1).
Внешних обращений нет. Применяется для image (:8291) и video (:8197) генераций.

    python cw_prompt_enhance.py "кот в космосе" [--lang en] [--model Qwen3-8B...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-stack"))
import config as C  # noqa: E402
import llama_client  # noqa: E402

SYSTEM = (
    "You are a prompt engineer for local ComfyUI text-to-image and text-to-video "
    "models (Stable Diffusion / Flux / MiniMax-style). Expand the user's short idea "
    "into ONE rich visual prompt: subject, style, lighting, camera, composition, "
    "quality tags. Output only the prompt text, 30-80 words, in {lang}."
)


def enhance(prompt: str, lang: str = "en", model: str | None = None) -> str:
    out = llama_client.chat(
        C.LLM_BASE_URL,
        model or C.DEFAULT_LLM_MODEL,
        [{"role": "system", "content": SYSTEM.format(lang=lang)},
         {"role": "user", "content": prompt}],
        temperature=0.7, max_tokens=300,
    )
    return out.strip().strip('"')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    try:
        print(enhance(a.prompt, a.lang, a.model))
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Локальный LLM :{C.LLM_PORT} недоступен? {e}\n"
                 "Запустите: cd local-stack && python start.py")


if __name__ == "__main__":
    main()
