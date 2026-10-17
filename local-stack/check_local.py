"""Проверка локального стека: все серверы живы, внешних AI API нет.

    python check_local.py
Выход 0 — стек полностью локален и готов.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
import llama_client  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Print a labeled result with optional detail and return ok unchanged."""
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def http_get(url: str) -> object | None:
    """GET and decode JSON, returning None on request or decoding errors.

    The URL policy check runs first and its RuntimeError propagates."""
    llama_client.assert_local(url)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    """Check configured services and return 0 on success, otherwise 1.

    ComfyUI availability is optional. Chat and embedding smoke tests run
    only when their model endpoints return JSON."""
    results = []

    models = http_get(f"{C.LLM_BASE_URL}/models")
    results.append(check("LLM llama-server :8484", models is not None,
                         "OpenAI-совместимый /v1 отвечает"))

    emodels = http_get(f"{C.EMBED_BASE_URL}/models")
    results.append(check("Embeddings llama-server :8512", emodels is not None))

    lancedb = http_get(f"{C.LANCEDB_URL}/health")
    results.append(check("LanceDB HTTP :8003", lancedb is not None))

    mcp = http_get(f"{C.MCP_URL}/health")
    results.append(check("MCP server :8001", mcp is not None))

    rm = http_get(f"{C.REPOMAPPER_URL}/health")
    results.append(check("RepoMapper :8002", rm is not None))

    comfy_img = http_get(f"{C.COMFY_IMAGE_URL}/system_stats")
    results.append(check("ComfyUI image :8291 (опция)", comfy_img is not None or True,
                         "не запущен — не блокирует" if comfy_img is None else "готов"))

    comfy_vid = http_get(f"{C.COMFY_VIDEO_URL}/system_stats")
    results.append(check("ComfyUI video :8197 (опция)", True,
                         "не запущен — не блокирует" if comfy_vid is None else "готов"))

    # LLM smoke test
    if models is not None:
        try:
            out = llama_client.chat(C.LLM_BASE_URL, "local", [{"role": "user", "content": "ping"}],
                                    max_tokens=8, timeout=120)
            results.append(check("LLM chat completion", bool(out)))
        except Exception as e:  # noqa: BLE001
            results.append(check("LLM chat completion", False, str(e)[:80]))

    # Embeddings smoke test
    if emodels is not None:
        try:
            vecs = llama_client.embed(C.EMBED_BASE_URL, "local", ["тест"], timeout=60)
            results.append(check("Embedding vector", len(vecs) == 1 and len(vecs[0]) > 0,
                                 f"dim={len(vecs[0]) if vecs else 0}"))
        except Exception as e:  # noqa: BLE001
            results.append(check("Embedding vector", False, str(e)[:80]))

    results.append(check("ALLOW_FREE_TIER выключен", not C.ALLOW_FREE_TIER,
                         "внешний free-tier fallback запрещён"))

    failed = [r for r in results if r is False]
    print(f"\nИтого: {len(results)} проверок, провалено: {len(failed)}")
    print("Внешних обращений к AI API в рантайме: 0 (все эндпоинты 127.0.0.1)")
    return 0 if len(failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
