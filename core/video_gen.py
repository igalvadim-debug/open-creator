"""core.video_gen — генерация видео через ЛОКАЛЬНЫЙ ComfyUI :8197.

Никаких Runway / Pika / Luma / MiniMax cloud API. Workflow из cwbuilder-docs:
  workflow_minimax_turbo_4step.json | _complete | workflow_minimax_video.json |
  workflow_magical_forest.json
Дефолтная модель: minimax_h3_fl2va_pruned_w6a8.safetensors + video VAE.
Разрешение 1024x1024, batch 1, timeout 3600s (config).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack", _ROOT / "cwbuilder-docs"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C  # noqa: E402
import llama_client as LC  # noqa: E402

SERVER = C.COMFY_VIDEO_URL   # http://127.0.0.1:8197


def workflow_path(name: str = "minimax_4step") -> Path:
    fn = C.CW_WORKFLOWS.get(name, name if name.endswith(".json") else C.CW_WORKFLOWS["minimax_4step"])
    p = Path(fn) if Path(fn).is_absolute() else C.CW_ROOT / fn
    if not p.exists():
        raise FileNotFoundError(f"Workflow не найден: {p}")
    return p


def build_workflow(prompt: str, *, name: str = "minimax_4step",
                   width: int = C.IMAGE_WIDTH, height: int = C.IMAGE_HEIGHT,
                   model: str = C.VIDEO_DEFAULT_MODEL, seed: int | None = None) -> dict:
    wf = json.loads(workflow_path(name).read_text(encoding="utf-8"))
    for n in wf.get("nodes", []):
        inp = n.setdefault("inputs", {})
        if isinstance(inp.get("text"), str) and "PROMPT_HERE" in inp["text"]:
            inp["text"] = prompt
        if "ckpt_name" in inp:
            inp["ckpt_name"] = model
        if "width" in inp:
            inp["width"] = width
        if "height" in inp:
            inp["height"] = height
        if "seed" in inp:
            inp["seed"] = seed if seed is not None else int(time.time()) % (2 ** 31)
    d = wf.get("defaults", {})
    d.update({"width": width, "height": height, "batch_size": C.GEN_BATCH_SIZE})
    wf["defaults"] = d
    return wf


def generate(prompt: str, out_path: str | Path, *, workflow: str = "minimax_4step",
             width: int = C.IMAGE_WIDTH, height: int = C.IMAGE_HEIGHT,
             model: str = C.VIDEO_DEFAULT_MODEL, enhance_prompt: bool = True,
             timeout: int = C.GEN_TIMEOUT_S) -> Path:
    """POST /prompt -> poll /history -> скачать результат. Только localhost."""
    LC.assert_local(SERVER)
    text = prompt
    if enhance_prompt:
        try:
            import cw_prompt_enhance
            text = cw_prompt_enhance.enhance(prompt)
        except Exception:  # noqa: BLE001
            pass
    wf = build_workflow(text, name=workflow, width=width, height=height, model=model)
    pid = uuid.uuid4().hex[:12]
    req = urllib.request.Request(f"{SERVER}/prompt",
                                 data=json.dumps({"prompt": wf, "client_id": pid}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        resp = json.loads(r.read().decode())
    ptask = resp.get("prompt_id") or pid

    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(f"{SERVER}/history/{ptask}", timeout=10) as r:  # noqa: S310
            hist = json.loads(r.read().decode())
        if ptask in hist:
            for node_out in hist[ptask].get("outputs", {}).values():
                for v in node_out.get("videos", []) + node_out.get("gifs", []) + node_out.get("images", []):
                    url = (f"{SERVER}/view?filename={v['filename']}"
                           f"&subfolder={v.get('subfolder', '')}&type={v.get('type', 'output')}")
                    out_path = Path(out_path)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with urllib.request.urlopen(url, timeout=300) as rr:  # noqa: S310
                        out_path.write_bytes(rr.read())
                    return out_path
            raise RuntimeError(f"ComfyUI :{C.COMFY_VIDEO_PORT} вернул пустой output")
        time.sleep(5)
    raise TimeoutError(f"Video gen timeout {timeout}s на {SERVER}")


__all__ = ["generate", "build_workflow", "workflow_path"]
