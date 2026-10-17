"""core.embedding_client — обёртка над ЛОКАЛЬНЫМ llama-server :8512.

embeddinggemma-300m-qat-Q8_0.gguf (фолбэк bge-m3-Q8_0.gguf), батчи по 8.
Free-tier fallback (внешний API) — только если ALLOW_FREE_TIER=1; по умолчанию
ЗАПРЕЩЁН и бросает RuntimeError.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C            # noqa: E402
import llama_client as LC     # noqa: E402

BASE_URL = C.EMBED_BASE_URL   # http://127.0.0.1:8512/v1


def embed(texts: list[str], *, timeout: float = 300.0) -> list[list[float]]:
    return LC.embed(BASE_URL, C.EMBED_MODEL, texts, timeout=timeout)


def embed_many(texts: Iterable[str]) -> list[list[float]]:
    return LC.embed_batched(BASE_URL, C.EMBED_MODEL, list(texts),
                            batch_size=C.INDEX_BATCH_SIZE)


def free_tier_embed_unsafe(texts: list[str]) -> list[list[float]]:
    """Единственный допустимый внешний канал. По умолчанию ВЫКЛЮЧЕН."""
    if not C.ALLOW_FREE_TIER:
        raise RuntimeError("ALLOW_FREE_TIER=0: внешние эмбеддинги запрещены политиком")
    raise NotImplementedError("Free-tier включён явно, но endpoint не настроен (.env)")


__all__ = ["embed", "embed_many", "BASE_URL"]
