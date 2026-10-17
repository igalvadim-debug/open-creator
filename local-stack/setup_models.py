"""Скачивание GGUF/моделей для локального стека (СЕТЬ ТОЛЬКО НА ЭТАПЕ УСТАНОВКИ).

Использование:
    python setup_models.py            # скачать всё недостающее
    python setup_models.py --list     # показать статус моделей
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

# HF-репозитории (только для первичной загрузки весов; в рантайме сеть не нужна)
HF_BASE = "https://huggingface.co"

DOWNLOADS: list[tuple[str, str]] = [
    # LLM
    ("QuantFactory/Qwen2.5-Coder-7B-Instruct-GGUF",
     "resolve/main/Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf"),
    ("bartowski/Qwen3-8B-GGUF", "resolve/main/Qwen3-8B-Q4_K_M.gguf"),
    ("unsloth/gemma-3n-E4B-it-GGUF", "resolve/main/gemma-3n-E4B-it-QAT-Q4_K_XL.gguf"),
    ("bartowski/Qwen3-4B-Instruct-2507-GGUF",
     "resolve/main/Qwen3-4B-Instruct-2507-Q8_0.gguf"),
    ("unsloth/gemma-3-4b-it-GGUF", "resolve/main/gemma-3-4b-it-qat-q4_0-gguf.gguf"),
    ("unsloth/gemma-3-4b-it-GGUF", "resolve/main/mmproj-gemma-3-4b-it-qat-F16.gguf"),
    # Embeddings
    ("ggml-org/embeddinggemma-300m-GGUF",
     "resolve/main/embeddinggemma-300m-qat-Q8_0.gguf"),
    ("CompendiumLabs/bge-m3-gguf", "resolve/main/bge-m3-Q8_0.gguf"),
]


def target_name(url_tail: str) -> str:
    """Return the final slash-separated component of a download URL tail."""
    return url_tail.rsplit("/", 1)[-1]


def download(repo: str, tail: str) -> Path:
    """Download a Hugging Face model to MODELS_DIR unless its path exists.

    Write through a .part file, then rename it to the destination. The parent
    directory must exist; HTTP and file errors propagate and may leave the
    partial file."""
    dest = C.MODELS_DIR / target_name(tail)
    if dest.exists():
        print(f"[skip] {dest.name} уже на месте")
        return dest
    url = f"{HF_BASE}/{repo}/{tail}"
    print(f"[get ] {url}\n       -> ./local-stack/models/{dest.name}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:  # noqa: S310 (HTTPS, HF)
        while True:
            chunk = r.read(1 << 22)
            if not chunk:
                break
            f.write(chunk)
    tmp.rename(dest)
    return dest


def status() -> None:
    """Print model file presence and guidance for Whisper and Piper voices."""
    missing = []
    for repo, tail in DOWNLOADS:
        p = C.MODELS_DIR / target_name(tail)
        mark = "OK " if p.exists() else "-- "
        print(f"[{mark}] models/{p.name}")
        if not p.exists():
            missing.append(p.name)
    for name in (C.WHISPER_MODEL,):
        print(f"[STT] faster-whisper '{name}' — скачается в ./local-stack/models/whisper при первом запуске")
    print(f"[TTS] голоса Piper -> ./local-stack/models/tts/{C.TTS_VOICE}.onnx (установка: pip install piper-tts && python -m piper.download_voices {C.TTS_VOICE})")
    if missing:
        print(f"\nНе хватает {len(missing)} файлов. Запустите: python setup_models.py")


def main() -> None:
    """Create directories and list model status or download missing models.

    Individual download exceptions are reported and processing continues."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="только статус")
    args = ap.parse_args()
    C.ensure_dirs()
    if args.list:
        status()
        return
    for repo, tail in DOWNLOADS:
        try:
            download(repo, tail)
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {target_name(tail)}: {e}")
    status()


if __name__ == "__main__":
    main()
