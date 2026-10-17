"""Минимальный OpenAI-совместимый клиент строго к ЛОКАЛЬНЫМ серверам.

Никаких внешних хостов: любой base_url, не указывающий на 127.0.0.1/localhost,
отклоняется (защита от случайного ухода в cloud). Только stdlib.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def assert_local(base_url: str) -> None:
    """Raise RuntimeError unless the URL contains a recognized local address
    substring, case-insensitively. This does not validate the parsed hostname."""
    low = base_url.lower()
    if not any(h in low for h in LOCAL_HOSTS):
        raise RuntimeError(
            f"POLICY: обращение к внешнему AI API запрещено ({base_url}). "
            "Разрешены только локальные серверы 127.0.0.1."
        )


def _post(url: str, payload: dict[str, Any], timeout: float = 600.0) -> dict[str, Any]:
    """POST JSON after the URL policy check and decode the JSON response.

    timeout is in seconds. Policy, serialization, HTTP, and response
    decoding errors propagate."""
    assert_local(url)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (url проверен)
        return json.loads(resp.read().decode("utf-8"))


def chat(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    timeout: float = 600.0,
) -> str:
    """Один chat-completion запрос; возвращает текст ответа."""
    data = _post(
        f"{base_url.rstrip('/')}/chat/completions",
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        },
        timeout=timeout,
    )
    return data["choices"][0]["message"]["content"]


def embed(base_url: str, model: str, texts: list[str], *, timeout: float = 300.0) -> list[list[float]]:
    """Эмбеддинги через /embeddings (llama-server --embedding)."""
    data = _post(
        f"{base_url.rstrip('/')}/embeddings",
        {"model": model, "input": texts},
        timeout=timeout,
    )
    items = sorted(data["data"], key=lambda d: d.get("index", 0))
    return [it["embedding"] for it in items]


def embed_batched(
    base_url: str, model: str, texts: Iterable[str], batch_size: int = 8, *, timeout: float = 300.0
) -> list[list[float]]:
    """Embed successive batches and concatenate vectors in batch order.

    timeout applies to each request in seconds. A nonpositive batch_size
    sends one text per request. Embedding errors propagate."""
    out: list[list[float]] = []
    batch: list[str] = []
    for t in texts:
        batch.append(t)
        if len(batch) >= batch_size:
            out.extend(embed(base_url, model, batch, timeout=timeout))
            batch = []
    if batch:
        out.extend(embed(base_url, model, batch, timeout=timeout))
    return out


def wait_ready(base_url: str, *, timeout: float = 120.0) -> bool:
    """Poll /models for HTTP 200 and return False when timeout seconds elapse.

    Requests have a separate three-second timeout, so this is not a strict
    wall-clock deadline. URL policy errors propagate; HTTP and OS errors
    are retried."""
    assert_local(base_url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url.rstrip('/')}/models", timeout=3) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    return False
