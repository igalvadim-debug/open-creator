"""core.video_download — yt-dlp (утилита, внешний сервис допустим).

Это НЕ AI-API: скачивание публичного видео остаётся как в оригинале.
Далее опционально: сразу транскрипция (локальный STT) -> перевод (LLM :8484)
-> дубляж (локальный TTS) -> сборка ffmpeg — см. pipelines/download_translate_dub.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C  # noqa: E402


def download(url: str, out_dir: str | Path = C.OUTPUT_DIR) -> Path:
    """Run yt-dlp into out_dir and return its most recently modified MP4.

    Create the directory if needed. Selection can include pre-existing MP4s.
    Raise RuntimeError if no MP4 is found; subprocess and file errors propagate."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    ydl = shutil.which("yt-dlp") or (C.BIN_DIR / ("yt-dlp" + (".exe" if sys.platform == "win32" else "")))
    if not ydl:
        raise RuntimeError("yt-dlp не найден. pip install yt-dlp (или ./local-stack/bin/yt-dlp)")
    tpl = str(out_dir / "%(title)s.%(ext)s")
    subprocess.run([str(ydl), "-f", "bv*+ba/b", "--merge-output-format", "mp4",
                    "-o", tpl, url], check=True)
    # самый свежий mp4 в out_dir
    files = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("yt-dlp завершился без файла")
    return files[0]


def get_title(url: str) -> str:
    """Return the stripped yt-dlp title output, or "video" if stdout is empty.

    A nonzero process status is ignored; process launch errors propagate."""
    ydl = shutil.which("yt-dlp") or (C.BIN_DIR / "yt-dlp")
    p = subprocess.run([str(ydl), "--print", "title", url], capture_output=True, text=True)
    return p.stdout.strip() or "video"


__all__ = ["download", "get_title"]
