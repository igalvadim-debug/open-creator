"""core.image_gen — генерация изображений через ЛОКАЛЬНЫЙ ComfyUI :8291.

Никаких DALL-E / SD-API / Midjourney. Модели берутся из cw_local_catalog.json
(checkpoints / diffusion_model_gguf / lora / vae / controlnet).
Промпт-энханс — cw_prompt_enhance.py (тот же локальный llama-server :8484).
Workflow подаётся как API-format JSON; плейсхолдер PROMPT_HERE заменяется.
"""
from __future__ import annotations

import json
import time
import urllib.request
import uuid
from pathlib import Path

import sys
_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack", _ROOT / "cwbuilder-docs"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C  # noqa: E402
import llama_client as LC  # noqa: E402

SERVER = C.COMFY_IMAGE_URL   # http://127.0.0.1:8291
DEFAULT_WORKFLOW = _ROOT / "config" / "workflows" / "image_default.json"


def catalog_models(category: str | None = None) -> list[dict]:
    if C.CW_CATALOG.exists():
        cat = json.loads(C.CW_CATALOG.read_text(encoding="utf-8"))
        ms = cat.get("models", [])
        return [m for m in ms if category is None or m.get("category") == category]
    return []


def enhance(prompt: str) -> str:
    """Локальный промпт-энхансер (:8484)."""
    try:
        import cw_prompt_enhance
        return cw_prompt_enhance.enhance(prompt)
    except Exception:  # noqa: BLE001 — если LLM недоступен, работаем с исходным
        return prompt


def build_workflow(prompt: str, *, width: int = C.IMAGE_WIDTH, height: int = C.IMAGE_HEIGHT,
                   seed: int | None = None, workflow_path: Path | None = None) -> dict:
    wf_file = workflow_path or DEFAULT_WORKFLOW
    wf = json.loads(Path(wf_file).read_text(encoding="utf-8"))
    nodes = wf.get("nodes", [])
    for n in nodes:
        inp = n.setdefault("inputs", {})
        if isinstance(inp.get("text"), str) and "PROMPT_HERE" in inp["text"]:
            inp["text"] = prompt
        if "width" in inp:
            inp["width"] = width
        if "height" in inp:
            inp["height"] = height
        if "seed" in inp:
            inp["seed"] = seed if seed is not None else int(time.time()) % (2 ** 31)
    return wf


def generate(prompt: str, out_path: str | Path, *, enhance_prompt: bool = True,
             width: int = C.IMAGE_WIDTH, height: int = C.IMAGE_HEIGHT,
             workflow_path: Path | None = None, timeout: int = C.GEN_TIMEOUT_S) -> Path:
    """POST /prompt -> ждать /history -> скачать /view. Только localhost."""
    LC.assert_local(SERVER)
    prompt_text = enhance(prompt) if enhance_prompt else prompt
    wf = build_workflow(prompt_text, width=width, height=height, workflow_path=workflow_path)
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
            outputs = hist[ptask].get("outputs", {})
            for node_out in outputs.values():
                for img in node_out.get("images", []) + node_out.get("gifs", []):
                    url = (f"{SERVER}/view?filename={img['filename']}"
                           f"&subfolder={img.get('subfolder', '')}&type={img.get('type', 'output')}")
                    out_path = Path(out_path)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with urllib.request.urlopen(url, timeout=60) as rr:  # noqa: S310
                        out_path.write_bytes(rr.read())
                    return out_path
            raise RuntimeError(f"ComfyUI :{C.COMFY_IMAGE_PORT} вернул пустой output")
        time.sleep(2)
    raise TimeoutError(f"Gen timeout {timeout}s на {SERVER}")


__all__ = ["generate", "enhance", "build_workflow", "catalog_models"]
