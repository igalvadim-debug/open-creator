"""agents.local_agent — Codex-подобный агент на ЛОКАЛЬНОЙ LLM (:8484).

Сохраняет механику оригинала: цикл «мысль -> инструмент -> наблюдение», но
бэкенд только локальный. Инструменты:
  - search_code / list_indexed_files / reindex  (MCP :8001 -> LanceDB :8003)
  - repo_map                                    (RepoMapper :8002, AST без LLM)
  - read_file / write_file / run_shell          (локальная песочница ./output)
Провайдер cloud недоступен по политике assert_local.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "local-stack",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as C            # noqa: E402
import llama_client as LC     # noqa: E402

SYSTEM_PROMPT = """Ты — локальный кодинг-агент open-creator (аналог Codex), работаешь
ТОЛЬКО с локальными инструментами. Отвечай строго JSON одного действия:
{"tool": "<имя>", "args": {...}} или {"final": "<ответ>"}.
Доступные инструменты:
- search_code {query, table?, k?}   векторный поиск по репозиторию (LanceDB+локальные эмбеддинги)
- list_indexed_files {table?}
- reindex {root?, tables?}
- repo_map {}                       AST-карта проекта (без LLM)
- read_file {path}
- write_file {path, content}       (только внутри ./output или корня репо)
- run_shell {cmd}                  (ffmpeg/yt-dlp/python; запрещены сетевые AI-вызовы)
"""


def _mcp(tool: str, args: dict) -> str:
    """Call an MCP tool and return its first text result.

    Policy, HTTP, JSON decoding, and missing-result errors propagate."""
    LC.assert_local(C.MCP_URL)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": tool, "arguments": args}}
    req = urllib.request.Request(C.MCP_URL, data=json.dumps(msg).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310
        out = json.loads(r.read().decode())
    return out["result"]["content"][0]["text"]


def _repo_map() -> str:
    """Fetch a repository map, limited to 80 files, eight signatures per file,
    and 12,000 characters. Policy, HTTP, and response parsing errors propagate."""
    LC.assert_local(C.REPOMAPPER_URL)
    with urllib.request.urlopen(f"{C.REPOMAPPER_URL}/map?root={_ROOT}", timeout=120) as r:  # noqa: S310
        d = json.loads(r.read().decode())
    lines = []
    for f, sigs in list(d["map"].items())[:80]:
        lines.append(f + "\n  " + "\n  ".join(sigs[:8]))
    return "\n".join(lines)[:12000]


def _safe_path(p: str) -> Path:
    """Resolve a path against the repository root; raise RuntimeError if it
    resolves outside that root, including through a symlink."""
    rp = (_ROOT / p).resolve()
    if _ROOT not in rp.parents and rp != _ROOT:
        raise RuntimeError("путь вне репозитория запрещён")
    return rp


def execute(tool: str, args: dict) -> str:
    """Run a named tool and return its text output.

    File reads and shell output are truncated to 20,000 characters. Writes
    create parent directories and replace files within the repository. Shell
    commands run from the repository root with a 600-second timeout; commands
    containing a forbidden substring return a rejection message. Unknown tools
    return a message. Tool, file, and subprocess errors propagate."""
    if tool in ("search_code", "list_indexed_files", "reindex"):
        return _mcp(tool, args)
    if tool == "repo_map":
        return _repo_map()
    if tool == "read_file":
        return _safe_path(args["path"]).read_text(encoding="utf-8", errors="replace")[:20000]
    if tool == "write_file":
        p = _safe_path(args["path"]); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"written {p}"
    if tool == "run_shell":
        forbidden = ("curl", "wget", "http://", "https://", "nc ", "ssh ")
        cmd = args["cmd"]
        if any(f in cmd for f in forbidden):
            return "REJECTED: сетевые вызовы агентом запрещены политикой локальности"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=600, cwd=str(_ROOT))
        return (r.stdout + r.stderr)[:20000]
    return f"unknown tool {tool}"


def parse_action(text: str) -> dict | None:
    """Decode the JSON between the first opening and last closing brace,
    after stripping an optional code fence. Return None for missing braces
    or invalid JSON; decoded values are not checked for an action schema."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").removeprefix("json").strip()
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        return json.loads(t[s:e + 1])
    except json.JSONDecodeError:
        return None


def run(task: str, *, max_steps: int = 10, model: str | None = None) -> str:
    """Run up to max_steps model/tool iterations and return the final answer.

    An unparseable response is returned verbatim. Exhausting the step limit
    returns a message with the last model response. Tool calls may write files
    or run shell commands; model and tool errors propagate."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task}]
    transcript = []
    for step in range(max_steps):
        raw = LC.chat(C.LLM_BASE_URL, model or C.CODING_MODEL, msgs,
                      temperature=0.2, max_tokens=1024)
        action = parse_action(raw)
        if not action or "final" in (action or {}):
            return (action or {}).get("final", raw)
        obs = execute(action.get("tool", ""), action.get("args", {}))
        transcript.append({"step": step, "action": action, "obs": obs[:500]})
        msgs += [{"role": "assistant", "content": raw},
                 {"role": "user", "content": f"OBSERVATION:\n{obs[:8000]}"}]
    return "max steps reached; последний ответ: " + (msgs[-2].get("content", "") if len(msgs) > 2 else "")


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Найди в репозитории модуль перевода и кратко опиши его"
    print(run(q))
