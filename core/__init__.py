"""core — локальные обёртки AI-сервисов open-creator.

Все модули ходят только на 127.0.0.1 (llama.cpp / ComfyUI / Whisper / Piper).
Внешние cloud API запрещены политикой (llama_client.assert_local).
"""
from __future__ import annotations

import sys
from pathlib import Path

# common/lokalnyy stack v syse.path dlya vseh modulей core
_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack", _ROOT / "cwbuilder-docs"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
