"""local-stack configuration — ALL endpoints are local (127.0.0.1).

Порты (согласно ТЗ):
  LLM            8484   OpenAI-совместимый /v1 (llama.cpp llama-server)
  Embeddings     8512   OpenAI-совместимый /v1/embeddings (llama.cpp llama-server)
  MCP (LanceDB)  8001   lancedb_mcp/server_local.py
  RepoMapper     8002   RepoMapper/http_repomapper.py
  LanceDB HTTP   8003   REST-обёртка над локальной LanceDB
  ComfyUI image  8291   (cwbuilder-docs)
  ComfyUI video  8197   (cwbuilder-docs)

Внешних обращений в рантайме: 0.
Free-tier fallback для эмбеддингов по умолчанию ВЫКЛЮЧЕН (ALLOW_FREE_TIER=0).
Сеть нужна только при первичной установке (setup_models.py).
"""
from __future__ import annotations

import os
from pathlib import Path

# --- пути (все относительные, кроссплатформенные) ---------------------------
ROOT = Path(__file__).resolve().parent.parent          # корень open-creator
STACK = ROOT / "local-stack"
MODELS_DIR = Path(os.environ.get("LOCAL_STACK_MODELS", str(STACK / "models")))
BIN_DIR = Path(os.environ.get("LOCAL_STACK_BIN", str(STACK / "bin")))
LOGS_DIR = ROOT / "logs"
OUTPUT_DIR = ROOT / "output"
LANCEDB_DIR = Path(os.environ.get("LANCEDB_DIR", str(ROOT / "lancedb_context")))

HOST = "127.0.0.1"

# --- порты -------------------------------------------------------------------
LLM_PORT = int(os.environ.get("LOCAL_LLM_PORT", "8484"))
EMBED_PORT = int(os.environ.get("LOCAL_EMBED_PORT", "8512"))
MCP_PORT = int(os.environ.get("LOCAL_MCP_PORT", "8001"))
REPOMAPPER_PORT = int(os.environ.get("LOCAL_REPOMAPPER_PORT", "8002"))
LANCEDB_PORT = int(os.environ.get("LOCAL_LANCEDB_PORT", "8003"))
COMFY_IMAGE_PORT = int(os.environ.get("COMFY_IMAGE_PORT", "8291"))
COMFY_VIDEO_PORT = int(os.environ.get("COMFY_VIDEO_PORT", "8197"))

LLM_BASE_URL = f"http://{HOST}:{LLM_PORT}/v1"
EMBED_BASE_URL = f"http://{HOST}:{EMBED_PORT}/v1"
MCP_URL = f"http://{HOST}:{MCP_PORT}"
REPOMAPPER_URL = f"http://{HOST}:{REPOMAPPER_PORT}"
LANCEDB_URL = f"http://{HOST}:{LANCEDB_PORT}"
COMFY_IMAGE_URL = f"http://{HOST}:{COMFY_IMAGE_PORT}"
COMFY_VIDEO_URL = f"http://{HOST}:{COMFY_VIDEO_PORT}"

# --- LLM модели (GGUF, llama.cpp) --------------------------------------------
LLM_MODELS: dict[str, str] = {
    # имя GGUF-файла (в MODELS_DIR) -> alias для OpenAI-совместимого API
    "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf": "qwen2.5-coder-7b",
    "Qwen3-8B-Q4_K_M.gguf": "qwen3-8b",
    "gemma-3n-E4B-it-QAT-Q4_K_XL.gguf": "gemma-3n-e4b",
    "Qwen3-4B-Instruct-2507-Q8_0.gguf": "qwen3-4b",
    "gemma-3-4b-it-qat-q4_0-gguf.gguf": "gemma-3-4b",   # + mmproj (vision)
}
VISION_MMPROJ = {
    "gemma-3-4b-it-qat-q4_0-gguf.gguf": "mmproj-gemma-3-4b-it-qat-F16.gguf",
}
DEFAULT_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "Qwen3-8B-Q4_K_M.gguf")
CODING_MODEL = os.environ.get("LOCAL_CODING_MODEL", "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")

LLM_CTX_SIZE = int(os.environ.get("LOCAL_LLM_CTX", "16384"))
LLM_NGL = int(os.environ.get("LOCAL_LLM_NGL", "99"))     # offload слоёв на GPU

# --- эмбеддинги ---------------------------------------------------------------
EMBED_MODEL_PRIMARY = "embeddinggemma-300m-qat-Q8_0.gguf"
EMBED_MODEL_FALLBACK = "bge-m3-Q8_0.gguf"
EMBED_MODEL = os.environ.get("LOCAL_EMBED_MODEL", EMBED_MODEL_PRIMARY)
EMBED_DIM = {"embeddinggemma-300m-qat-Q8_0.gguf": 768, "bge-m3-Q8_0.gguf": 1024}.get(
    EMBED_MODEL, 768
)
# Free-tier fallback (внешний API) — по умолчанию ВЫКЛЮЧЕН.
ALLOW_FREE_TIER = os.environ.get("ALLOW_FREE_TIER", "0") not in ("0", "", "false", "False")

# --- индексация (механика local-stack) ----------------------------------------
INDEX_CHUNK_LINES = 30      # блоки по 30 строк
INDEX_BATCH_SIZE = 8        # батчи эмбеддингов по 8

# --- перевод ------------------------------------------------------------------
TRANSLATION_LANGS = ("ru", "de", "en")
TRANSLATION_PROMPT_FILE = ROOT / "config" / "prompts" / "translation.txt"

# --- STT / TTS ----------------------------------------------------------------
WHISPER_MODEL = os.environ.get("LOCAL_WHISPER_MODEL", "base")  # base|small|medium
WHISPER_MODELS_DIR = STACK / "models" / "whisper"
TTS_BACKEND = os.environ.get("LOCAL_TTS_BACKEND", "piper")     # piper|coqui|f5tts|openai_compat
TTS_VOICE = os.environ.get("LOCAL_TTS_VOICE", "ru_RU-ruslan-medium")
TTS_MODEL_PATH = os.environ.get("LOCAL_TTS_MODEL_PATH", str(STACK / "models" / "tts"))
TTS_SPEED = float(os.environ.get("LOCAL_TTS_SPEED", "1.0"))
TTS_SPEAKER = os.environ.get("LOCAL_TTS_SPEAKER", "default")
# Локальный OpenAI-совместимый TTS-сервер (если поднят отдельно), опционально.
TTS_OPENAI_BASE = os.environ.get("LOCAL_TTS_OPENAI_BASE", f"http://{HOST}:{LLM_PORT}/v1")

# --- ComfyUI / cwbuilder-docs ---------------------------------------------------
CW_ROOT = ROOT / "cwbuilder-docs"
CW_CATALOG = CW_ROOT / "cw_local_catalog.json"
CW_COMFY_LOCAL = CW_ROOT / "ComfyUI-local"
CW_WORKFLOWS = {
    "minimax_4step": "workflow_minimax_turbo_4step.json",
    "minimax_complete": "workflow_minimax_complete.json",
    "minimax_video": "workflow_minimax_video.json",
    "magical_forest": "workflow_magical_forest.json",
}
VIDEO_DEFAULT_MODEL = "minimax_h3_fl2va_pruned_w6a8.safetensors"
IMAGE_WIDTH = int(os.environ.get("GEN_WIDTH", "1024"))
IMAGE_HEIGHT = int(os.environ.get("GEN_HEIGHT", "1024"))
GEN_BATCH_SIZE = 1
GEN_TIMEOUT_S = 3600


def ensure_dirs() -> None:
    """Create configured model, binary, log, output, and database directories."""
    for d in (MODELS_DIR, BIN_DIR, LOGS_DIR, OUTPUT_DIR, LANCEDB_DIR):
        d.mkdir(parents=True, exist_ok=True)


# --- LOCAL-FIRST инварианты ---------------------------------------------------
# Конфигурация валидируется при импорте: процесс падает сразу с понятным
# сообщением, а не позже — запросом к внешнему API.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_local_config() -> list[str]:
    """Return a list of local-first policy violations (empty list = OK).

    Проверяет, что все HTTP-эндпоинты стека указывают на loopback-хосты и
    что серверы биндятся только локально."""
    from urllib.parse import urlparse

    problems: list[str] = []
    urls = {
        "LLM_BASE_URL": LLM_BASE_URL,
        "EMBED_BASE_URL": EMBED_BASE_URL,
        "MCP_URL": MCP_URL,
        "REPOMAPPER_URL": REPOMAPPER_URL,
        "LANCEDB_URL": LANCEDB_URL,
        "COMFY_IMAGE_URL": COMFY_IMAGE_URL,
        "COMFY_VIDEO_URL": COMFY_VIDEO_URL,
        "TTS_OPENAI_BASE": TTS_OPENAI_BASE,
    }
    for name, url in urls.items():
        try:
            host = urlparse(url).hostname or ""
        except ValueError as exc:
            problems.append(f"{name}={url}: некорректный URL ({exc})")
            continue
        if host not in _LOCAL_HOSTS:
            problems.append(f"{name}={url}: хост '{host}' не является loopback")
    if HOST not in _LOCAL_HOSTS:
        problems.append(f"HOST={HOST}: серверы нельзя биндить вне loopback")
    return problems


if os.environ.get("OPENCREATOR_LOCAL", "").lower() in ("1", "true", "yes"):
    _violations = validate_local_config()
    if _violations:
        raise SystemExit(
            "OPENCREATOR_LOCAL=1, но конфигурация локального стека нарушена:\n  - "
            + "\n  - ".join(_violations)
        )
