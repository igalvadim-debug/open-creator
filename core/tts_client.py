"""core.tts_client — ЛОКАЛЬНЫЙ TTS (Piper / Coqui XTTS-v2 / F5-TTS).

Никаких ElevenLabs / OpenAI TTS / Volcengine. Настройки голоса — из
config/config.local.json (backend, voice model path, language, speaker).
Если в cwbuilder-docs каталоге есть tts-модели — используются в первую очередь.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C  # noqa: E402

CFG_FILE = _ROOT / "config" / "config.local.json"


def load_cfg() -> dict:
    cfg = {"backend": C.TTS_BACKEND, "voice": C.TTS_VOICE,
           "model_path": C.TTS_MODEL_PATH, "language": "ru",
           "speaker": C.TTS_SPEAKER, "speed": C.TTS_SPEED}
    if CFG_FILE.exists():
        user = json.loads(CFG_FILE.read_text(encoding="utf-8")).get("tts", {})
        cfg.update(user)
    # приоритет: tts-модели из локального ComfyUI-каталога cwbuilder-docs
    cw_tts = C.CW_COMFY_LOCAL / "tts"
    if cw_tts.is_dir():
        onnx = sorted(cw_tts.glob(f"*{cfg['language']}*.onnx")) or sorted(cw_tts.glob("*.onnx"))
        if onnx:
            cfg["model_path"] = str(onnx[0].parent)
            cfg["voice"] = onnx[0].stem
            cfg["backend"] = "piper"
    return cfg


def synth(text: str, out_path: str | Path) -> Path:
    """Озвучить текст локально -> wav. Внешних вызовов: 0."""
    cfg = load_cfg()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    backend = cfg["backend"].lower()

    if backend == "piper":
        voices_dir = Path(cfg["model_path"])
        model = voices_dir / f"{cfg['voice']}.onnx"
        if not model.exists():
            model = voices_dir / cfg["voice"] / f"{cfg['voice']}.onnx"
        exe = shutil.which("piper") or (C.BIN_DIR / ("piper" + (".exe" if sys.platform == "win32" else "")))
        if not exe or not model.exists():
            raise RuntimeError(
                f"Piper не найден (бинарь ./local-stack/bin/piper, модель {model}). "
                f"Установка: pip install piper-tts && python -m piper.download_voices {cfg['voice']} "
                f"--data-dir ./local-stack/models/tts")
        p = subprocess.run([str(exe), "-m", str(model), "-f", str(out_path),
                            "--length_scale", str(1.0 / float(cfg.get("speed", 1.0)))],
                           input=text.encode(), capture_output=True)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.decode()[:300])
        return out_path

    if backend in ("coqui", "xtts"):
        from TTS.api import TTS  # type: ignore (coqui-tts, локальные веса)
        t = TTS(model_name="tts", lang_to_lang_path=None) if False else \
            TTS("tts_models/ru/cv/vits")  # базовая локальная модель; XTTS-v2 — через model_path
        mp = Path(cfg["model_path"])
        if mp.exists() and any(mp.rglob("*XTTS*")):
            t = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2",
                    device="cpu").to("cpu")
            t.tts_to_file(text=text, file_path=str(out_path),
                          language=cfg["language"], speaker_wav=str(mp / "reference.wav"),
                          speed=float(cfg.get("speed", 1.0)))
            return out_path
        t.tts_to_file(text=text, file_path=str(out_path), language=cfg["language"])
        return out_path

    if backend == "f5tts":
        # F5-TTS запускается как локальный CLI/сервер — см. README_LOCAL.md
        exe = C.BIN_DIR / "f5-tts"
        subprocess.run([str(exe), "--text", text, "--output", str(out_path),
                        "--lang", cfg["language"], "--speaker", cfg["speaker"]], check=True)
        return out_path

    if backend == "openai_compat":
        # локальный OpenAI-совместимый TTS-сервер (например, coqui-server на 127.0.0.1)
        import llama_client as LC
        LC.assert_local(cfg.get("base_url", C.TTS_OPENAI_BASE))
        import urllib.request
        req = urllib.request.Request(
            f"{cfg.get('base_url', C.TTS_OPENAI_BASE).rstrip('/')}/audio/speech",
            data=json.dumps({"model": cfg.get("model", "tts-1"), "input": text,
                             "voice": cfg["voice"], "speed": cfg.get("speed", 1.0)}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310 (127.0.0.1)
            out_path.write_bytes(r.read())
        return out_path

    raise RuntimeError(f"Неизвестный TTS backend: {backend}")


def synth_lines(segs: list[dict], out_base: str | Path) -> list[Path]:
    """Дубляж сегментов (с таймингами STT) -> набор wav."""
    out_base = Path(out_base); out_base.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for i, s in enumerate(segs):
        p = out_base.parent / f"{out_base.stem}_{i:05d}.wav"
        files.append(synth(s["text"], p))
    return files


__all__ = ["synth", "synth_lines", "load_cfg"]
