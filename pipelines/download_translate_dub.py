#!/usr/bin/env python3
"""Pipeline: скачать видео -> транскрипция -> перевод -> дубляж -> сборка.

ВСЁ AI — локально: STT (faster-whisper), перевод (LLM :8484), TTS (Piper/Coqui),
сборка — ffmpeg. Внешний сервис только yt-dlp (загрузка публичного видео).

    python pipelines/download_translate_dub.py --url <video_url> [--dst ru|de|en]
                                               [--video path.mp4] [--no-dub]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import stt_client, translation, tts_client  # noqa: E402
from core import video_download  # noqa: E402
import config as C  # noqa: E402


def assemble(video: Path, wav_files: list[Path], segs: list[dict], out: Path) -> Path:
    """Склейка дубляжа по таймингам + подмена аудио дорожки (ffmpeg)."""
    ff = shutil.which("ffmpeg") or (C.BIN_DIR / "ffmpeg")
    # 1) одна дорожка дубляжа: adelay каждого сегмента + amix
    inputs, filters = [], []
    for i, (w, s) in enumerate(zip(wav_files, segs)):
        inputs += ["-i", str(w)]
        ms = int(s["start"] * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms}[a{i}]")
    n = len(wav_files)
    if n == 0:
        shutil.copy(video, out); return out
    mix = "".join(f"[a{i}]" for i in range(n))
    filters.append(f"{mix}amix=inputs={n}:duration=longest:normalize=0[mix]")
    cmd = [str(ff), "-y", "-i", str(video)] + inputs + \
          ["-filter_complex", ";".join(filters),
           "-map", "0:v", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def run(url: str | None, video_path: str | None, dst: str, dub: bool, src: str) -> None:
    C.ensure_dirs()
    out_dir = C.OUTPUT_DIR / "dub"
    out_dir.mkdir(parents=True, exist_ok=True)

    if url and not video_path:
        print(f"[1/5] Скачивание: {url}")
        video = video_download.download(url, out_dir)
    else:
        video = Path(video_path)  # type: ignore[arg-type]
    print(f"      видео: {video}")

    print("[2/5] Извлечение аудио + локальная транскрипция (Whisper)")
    wav = stt_client.extract_audio(video)
    segs = stt_client.transcribe(wav)
    base = out_dir / (video.stem + ".orig")
    subs = stt_client.write_outputs(segs, base)
    print(f"      сегментов: {len(segs)}; субтитры: {subs['srt']}")

    print(f"[3/5] Локальный перевод -> {dst} (LLM :{C.LLM_PORT})")
    tr_segs = translation.translate_srt(segs, src, dst)
    tr_base = out_dir / (video.stem + f".{dst}")
    tr_subs = stt_client.write_outputs(tr_segs, tr_base)
    print(f"      субтитры: {tr_subs['srt']}")

    if not dub:
        print("[4/5] Дубляж пропущен (--no-dub). Готово.")
        return

    print(f"[4/5] Локальный дубляж TTS ({tts_client.load_cfg()['backend']})")
    wavs = tts_client.synth_lines(tr_segs, out_dir / (video.stem + ".dub"))
    print(f"      озвучено сегментов: {len(wavs)}")

    print("[5/5] Сборка (ffmpeg): видео + дорожка дубляжа")
    final = out_dir / (video.stem + f".dubbed.{dst}.mp4")
    assemble(video, wavs, tr_segs, final)
    print(f"ГОТОВО: {final}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--video", help="уже скачанный файл mp4")
    ap.add_argument("--dst", default="ru", choices=list(C.TRANSLATION_LANGS))
    ap.add_argument("--src", default="auto")
    ap.add_argument("--no-dub", action="store_true", help="только субтитры")
    a = ap.parse_args()
    if not a.url and not a.video:
        ap.error("нужен --url или --video")
    run(a.url, a.video, a.dst, not a.no_dub, a.src)


if __name__ == "__main__":
    main()
