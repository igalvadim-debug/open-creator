"""core.translation — ЛОКАЛЬНЫЙ перевод через LLM :8484.

Никаких DeepL / Google Translate. Промпт вынесен в config/prompts/translation.txt.
Поддерживаются ru/de/en (расширяемо списком в конфиге). Для коротких строк —
батчинг нумерованными блоками, чтобы локальная модель не «съезжала».
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C  # noqa: E402
from core import llm_client  # noqa: E402

PROMPT_FILE = C.TRANSLATION_PROMPT_FILE
LANG_NAMES = {"ru": "Russian", "de": "German", "en": "English"}


def load_prompt_template() -> str:
    """Read the translation prompt, or return the built-in template if absent.

    File read errors propagate."""
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return ("Translate the numbered lines from {src_name} to {dst_name}. "
            "Keep numbering, timing and line count EXACTLY. Output only translated lines.")


def translate(text: str, src: str = "auto", dst: str = "ru", *,
              model: str | None = None) -> str:
    """Перевод произвольного текста локальной LLM."""
    tpl = load_prompt_template()
    system = tpl.format(src_name=src.upper() if src != "auto" else "source language",
                        dst_name=LANG_NAMES.get(dst, dst))
    return llm_client.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": text}],
        model=model or C.DEFAULT_LLM_MODEL, temperature=0.2, max_tokens=4096)


def translate_lines(lines: list[str], src: str = "auto", dst: str = "ru",
                    batch: int = 20, model: str | None = None) -> list[str]:
    """Translate numbered batches and return one output per input line.

    Missing numbered translations retain the original line. src="auto" asks
    the model to infer the source language. batch must be positive: zero
    raises ValueError, while a negative value produces no batches. Prompt
    formatting, file, and model request errors propagate."""
    out: list[str] = []
    tpl = load_prompt_template()
    system = tpl.format(src_name=src.upper() if src != "auto" else "source language",
                        dst_name=LANG_NAMES.get(dst, dst))
    for i in range(0, len(lines), batch):
        chunk = lines[i:i + batch]
        numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(chunk))
        raw = llm_client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": numbered}],
            model=model or C.DEFAULT_LLM_MODEL, temperature=0.2, max_tokens=4096)
        parsed = {}
        for m in re.finditer(r"^\s*(\d+)[.)]\s*(.+)$", raw, flags=re.M):
            parsed[int(m.group(1))] = m.group(2).strip()
        for j in range(len(chunk)):
            out.append(parsed.get(j + 1, chunk[j]))   # фолбэк: оригинал, если модель потеряла строку
    return out


def translate_srt(segs: list[dict], src: str, dst: str,
                  model: str | None = None) -> list[dict]:
    """Return copies of segments with translated text and text_orig added,
    preserving timestamps and other fields. Missing translations retain the
    original text; translation errors propagate."""
    texts = [s["text"] for s in segs]
    tr = translate_lines(texts, src, dst, model=model)
    return [{**s, "text_orig": s["text"], "text": t} for s, t in zip(segs, tr)]


__all__ = ["translate", "translate_lines", "translate_srt", "load_prompt_template"]
