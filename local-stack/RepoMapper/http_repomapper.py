"""RepoMapper (порт 8002) — AST-карта проекта БЕЗ LLM и без сети.

GET /health, GET /map?root=./&lang=py|ts — дерево файлов + сигнатуры
(функции/классы/экспорты). Используется агентами как дешёвый контекст кода.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402

SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".venv", "models",
             "bin", "logs", "output", "lancedb_context", "ComfyUI-local", "runtime"}
TS_SIG_RE = re.compile(
    r"^\s*(export\s+)?(async\s+)?(function|class|const|interface|type|enum)\s+([A-Za-z0-9_]+)"
)


def map_python(f: Path) -> list[str]:
    try:
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    sigs = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ", ".join(a.arg for a in node.args.args)
            sigs.append(f"def {node.name}({args})")
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(getattr(b, "id", getattr(b, "attr", "?")) for b in node.bases)
            methods = [m.name for m in node.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            sigs.append(f"class {node.name}({bases}) {{{', '.join(methods[:12])}}}")
    return sigs


def map_ts(f: Path) -> list[str]:
    sigs = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TS_SIG_RE.match(line)
        if m:
            sigs.append(line.strip()[:160])
    return sigs[:200]


def build_map(root: Path) -> dict:
    out: dict[str, list[str]] = {}
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if p.suffix == ".py":
            s = map_python(p)
        elif p.suffix in (".ts", ".tsx", ".js", ".jsx"):
            s = map_ts(p)
        else:
            continue
        if s:
            out[rel] = s
    return {"root": str(root), "files": len(out), "map": out}


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/health"):
            self._send({"ok": True, "local": True, "llm_used": False})
        elif self.path.startswith("/map"):
            raw_root = C.ROOT
            if "root=" in self.path:
                raw_root = Path(self.path.split("root=")[1].split("&")[0])
            self._send(build_map(Path(raw_root).resolve()))
        else:
            self._send({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        sys.stderr.write("[repomapper-8002] " + fmt % args + "\n")


def main() -> None:
    srv = ThreadingHTTPServer((C.HOST, C.REPOMAPPER_PORT), Handler)
    print(f"RepoMapper (AST, no-LLM) on http://{C.HOST}:{C.REPOMAPPER_PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
