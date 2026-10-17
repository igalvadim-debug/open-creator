"""core.llm_client — обёртка над ЛОКАЛЬНЫМ llama-server :8484.

Все агенты/перевод/энханс идут сюда. Внешние cloud LLM запрещены политикой
(llama_client.assert_local). Пакет local-stack добавляется в sys.path
автоматически, чтобы не дублировать код (интеграция, не переписывание).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C            # noqa: E402
import llama_client as LC     # noqa: E402

BASE_URL = C.LLM_BASE_URL     # http://127.0.0.1:8484/v1


def chat(messages: list[dict[str, str]], *, model: str | None = None,
         temperature: float = 0.3, max_tokens: int = 2048, timeout: float = 600.0) -> str:
    """Один запрос к локальной LLM (:8484)."""
    return LC.chat(BASE_URL, model or C.DEFAULT_LLM_MODEL, messages,
                   temperature=temperature, max_tokens=max_tokens, timeout=timeout)


def complete(prompt: str, *, model: str | None = None, system: str | None = None,
             **kw) -> str:
    """Send a user prompt with an optional system message and return the reply.

    Extra keyword arguments are passed to chat; its errors propagate."""
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    return chat(msgs, model=model, **kw)


def is_ready(timeout: float = 5.0) -> bool:
    """Poll with timeout in seconds and return True unless polling raises.

    A False result from the underlying readiness poll is ignored, so True
    does not establish server readiness. Exceptions are converted to False."""
    try:
        LC.wait_ready(BASE_URL, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


__all__ = ["chat", "complete", "is_ready", "BASE_URL", "C"]
