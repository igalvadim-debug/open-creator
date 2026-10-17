"""core.stt_client — ЛОКАЛЬНАЯ транскрипция (faster-whisper / whisper.cpp).

Никаких Whisper API / AssemblyAI. Модель base/small/medium выбирается по VRAM
(LOCAL_WHISPER_MODEL). Выход: srt/vtt/txt для перевода и дубляжа.
Сеть: только первичная загрузка весов faster-whisper в ./local-stack/models/whisper.
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

_model = None


def _get_whisper():
    """Return a cached faster-whisper model, downloading weights if needed.

    Raise RuntimeError if faster-whisper cannot be imported; model loading
    and file errors propagate."""
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError:
            raise RuntimeError(
                "pip install faster-whisper  (или положите whisper-cli в ./local-stack/bin)")
        C.WHISPER_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        _model = WhisperModel(C.WHISPER_MODEL, device="auto",
                              compute_type="auto",
                              download_root=str(C.WHISPER_MODELS_DIR))
    return _model


def _fmt_ts(t: float) -> str:
    """Format seconds as an SRT timestamp with a comma and three decimals."""
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def transcribe(audio_path: str | Path) -> list[dict]:
    """Return transcription segments with start/end times in seconds and text.

    Prefer installed whisper-cli and weights, writing a sibling transcript;
    otherwise use faster-whisper, which may download missing weights. Model,
    subprocess, file, and transcript parsing errors propagate."""
    audio_path = Path(audio_path)
    cli = C.BIN_DIR / ("whisper-cli" + (".exe" if sys.platform == "win32" else ""))
    gguf = C.WHISPER_MODELS_DIR / f"ggml-{C.WHISPER_MODEL}.bin"
    if cli.exists() and gguf.exists():          # путь whisper.cpp — вообще без python-зависимостей
        out_txt = audio_path.with_suffix(".whisper.txt")
        subprocess.run([str(cli), "-m", str(gguf), str(audio_path), "-otxt",
                        "-of", str(out_txt.with_suffix(""))], check=True)
        segs, cur = [], None
        for line in out_txt.read_text(encoding="utf-8", errors="replace").splitlines():
            if "[" in line and "]" in line and "-->" in line:
                ts = line[line.index("[") + 1: line.index("]")].split("-->")
                cur = {"start": float(ts[0]), "end": float(ts[1]), "text": ""}
                segs.append(cur)
            elif cur is not None and line.strip():
                cur["text"] += (" " if cur["text"] else "") + line.strip()
        return segs
    model = _get_whisper()
    segments, _info = model.transcribe(str(audio_path), vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]


def to_srt(segs: list[dict]) -> str:
    """Render segments with start/end times in seconds as numbered SRT cues."""
    lines = []
    for i, s in enumerate(segs, 1):
        lines += [str(i), f"{_fmt_ts(s['start'])} --> {_fmt_ts(s['end'])}", s["text"], ""]
    return "\n".join(lines)


def to_vtt(segs: list[dict]) -> str:
    """Render segments under a WEBVTT header using the current timestamp
    formatter, which retains commas and appends zeros."""
    lines = ["WEBVTT", ""]
    for s in segs:
        lines += [f"{_fmt_ts(s['start'])[:-1]}000 --> {_fmt_ts(s['end'])[:-1]}000",
                  s["text"], ""]
    return "\n".join(lines)


def write_outputs(segs: list[dict], base: str | Path) -> dict[str, str]:
    """Write SRT, VTT, and plain text files and return their paths by extension.

    Replace the suffix of base, create parent directories, and overwrite
    existing files. File and segment formatting errors propagate."""
    base = Path(base); base.parent.mkdir(parents=True, exist_ok=True)
    outs = {}
    for ext, content in (("srt", to_srt(segs)), ("vtt", to_vtt(segs)),
                         ("txt", "\n".join(s["text"] for s in segs))):
        p = base.with_suffix("." + ext)
        p.write_text(content, encoding="utf-8")
        outs[ext] = str(p)
    return outs


def extract_audio(video_path: str | Path) -> Path:
    """Return a sibling .16k.wav file, creating 16 kHz mono audio with ffmpeg
    only if that path is absent. File and subprocess errors propagate."""
    video_path = Path(video_path)
    wav = video_path.with_suffix(".16k.wav")
    if not wav.exists():
        ff = shutil.which("ffmpeg") or (C.BIN_DIR / "ffmpeg")
        subprocess.run([str(ff), "-y", "-i", str(video_path), "-ar", "16000",
                        "-ac", "1", str(wav)], check=True, capture_output=True)
    return wav


__all__ = ["transcribe", "to_srt", "to_vtt", "write_outputs", "extract_audio"]
