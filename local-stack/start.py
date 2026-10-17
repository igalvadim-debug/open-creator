"""Запуск локального стека: llama-server'ы + LanceDB HTTP + MCP + RepoMapper.

    python start.py            # поднять все серверы (фоновые процессы)
    python start.py --stop     # остановить
Локальные бинари: ./local-stack/bin/llama-server (см. README_LOCAL.md).
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

PIDFILE = C.STACK / ".pids"


def find_llama_server() -> str:
    """Find llama-server in the configured bin directory, then PATH; raise
    SystemExit when no candidate is found."""
    for cand in (C.BIN_DIR / "llama-server", C.BIN_DIR / "llama-server.exe"):
        if cand.exists():
            return str(cand)
    from shutil import which
    w = which("llama-server")
    if w:
        return w
    raise SystemExit(
        "llama-server не найден. Положите бинарь в ./local-stack/bin/ "
        "(сборка llama.cpp или релиз ggml-org/llama.cpp)."
    )


def pick_model() -> str:
    """Return the configured model path if present, otherwise the first sorted
    GGUF whose name lacks mmproj. Raise SystemExit when none is found."""
    primary = C.MODELS_DIR / C.DEFAULT_LLM_MODEL
    if primary.exists():
        return str(primary)
    for p in sorted(C.MODELS_DIR.glob("*.gguf")):
        if "mmproj" not in p.name.lower():
            return str(p)
    raise SystemExit(f"В ./local-stack/models нет GGUF-моделей. Запустите python setup_models.py")


def pick_embed_model() -> str:
    """Return the primary embedding model path or its fallback; raise
    SystemExit when neither exists."""
    for name in (C.EMBED_MODEL_PRIMARY, C.EMBED_MODEL_FALLBACK):
        p = C.MODELS_DIR / name
        if p.exists():
            return str(p)
    raise SystemExit("Нет embedding-модели (embeddinggemma/bge-m3). python setup_models.py")


def spawn(cmd: list[str], log: Path) -> subprocess.Popen:
    """Start a command from the repository root, appending stdout and stderr
    to log, and return its process handle. File and launch errors propagate."""
    fh = open(log, "ab")
    p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=str(C.ROOT))
    print(f"[start] {' '.join(cmd[:4])}... -> logs/{log.name} (pid {p.pid})")
    return p


def start() -> None:
    """Launch the five stack processes and record their PIDs.

    Poll LLM and embedding readiness without failing on a False result.
    Model lookup, launch, and file errors propagate; previously started
    processes are not cleaned up when a later step fails."""
    C.ensure_dirs()
    ls = find_llama_server()
    procs = []
    # 1) LLM :8484
    procs.append(spawn(
        [ls, "-m", pick_model(), "--host", C.HOST, "--port", str(C.LLM_PORT),
         "-c", str(C.LLM_CTX_SIZE), "-ngl", str(C.LLM_NGL)],
        C.LOGS_DIR / "llm-8484.log"))
    # 2) Embeddings :8512
    procs.append(spawn(
        [ls, "-m", pick_embed_model(), "--host", C.HOST, "--port", str(C.EMBED_PORT),
         "--embedding", "--embd-normalize", "-2"],
        C.LOGS_DIR / "embed-8512.log"))
    # 3) LanceDB HTTP :8003
    procs.append(spawn([sys.executable, str(C.STACK / "lancedb_mcp" / "db_http.py")],
                       C.LOGS_DIR / "lancedb-8003.log"))
    # 4) MCP :8001
    procs.append(spawn([sys.executable, str(C.STACK / "lancedb_mcp" / "server_local.py")],
                       C.LOGS_DIR / "mcp-8001.log"))
    # 5) RepoMapper :8002
    procs.append(spawn([sys.executable, str(C.STACK / "RepoMapper" / "http_repomapper.py")],
                       C.LOGS_DIR / "repomapper-8002.log"))

    PIDFILE.write_text("\n".join(str(p.pid) for p in procs))
    print("\nОжидаю готовности LLM :8484 ...")
    import llama_client
    if llama_client.wait_ready(C.LLM_BASE_URL, timeout=300):
        print("[ok] LLM 8484 готов")
    else:
        print("[warn] LLM 8484 не ответил — см. logs/llm-8484.log")
    if llama_client.wait_ready(C.EMBED_BASE_URL, timeout=120):
        print("[ok] Embeddings 8512 готовы")
    print("\nВсе серверы локальны (127.0.0.1). Внешних AI-вызовов: 0.")


def stop() -> None:
    """Send SIGTERM to recorded PIDs and remove the PID file without waiting.

    Missing processes and invalid PID lines are ignored. Other signal and
    file errors propagate; a missing PID file is a no-op."""
    if not PIDFILE.exists():
        print("нет .pids — останавливать нечего")
        return
    for line in PIDFILE.read_text().splitlines():
        try:
            os.kill(int(line), signal.SIGTERM)
            print(f"[stop] pid {line}")
        except (ProcessLookupError, ValueError):
            pass
    PIDFILE.unlink(missing_ok=True)


def main() -> None:
    """Start the stack, or signal recorded processes when --stop is supplied."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()
    if args.stop:
        stop()
    else:
        start()


if __name__ == "__main__":
    main()
