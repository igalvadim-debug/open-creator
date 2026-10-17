"""MCP-сервер поверх локальной LanceDB (порт 8001).

Инструменты: search_code / list_indexed_files / reindex — все запросы идут
в локальный LanceDB HTTP :8003 и эмбеддинги :8512. Внешних вызовов нет.

Реализация: лёгкий JSON-RPC поверх HTTP (MCP streamable-http совместимый
 handshake упрощён: tools/call + initialize + tools/list).
"""
from __future__ import annotations

import json
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
import llama_client  # noqa: E402

TOOLS = {
    "search_code": {
        "description": "Векторный поиск по проиндексированному коду/контенту (LanceDB + локальные эмбеддинги)",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "table": {"type": "string", "enum": ["code", "content"]},
            "k": {"type": "integer"}}, "required": ["query"]},
    },
    "list_indexed_files": {
        "description": "Список файлов в индексе",
        "inputSchema": {"type": "object", "properties": {
            "table": {"type": "string", "enum": ["code", "content"]}}},
    },
    "reindex": {
        "description": "Инкрементальная переиндексация (sha1+mtime кэш, чанки 30 строк, батчи 8)",
        "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string"},
            "tables": {"type": "array", "items": {"type": "string"}}}},
    },
}


def _rpc(method: str, params: dict) -> object:
    llama_client.assert_local(C.LANCEDB_URL)
    url = f"{C.LANCEDB_URL}/{method}"
    data = json.dumps(params).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310 (127.0.0.1)
        return json.loads(r.read().decode())


def call_tool(name: str, args: dict) -> str:
    if name == "search_code":
        res = _rpc("search", {"table": args.get("table", "code"),
                              "query": args.get("query", ""), "k": args.get("k", 8)})
        return json.dumps(res, ensure_ascii=False)
    if name == "list_indexed_files":
        table = args.get("table", "code")
        llama_client.assert_local(C.LANCEDB_URL)
        with urllib.request.urlopen(f"{C.LANCEDB_URL}/files?table={table}", timeout=60) as r:  # noqa: S310
            return r.read().decode()
    if name == "reindex":
        res = _rpc("reindex", {"root": args.get("root", str(C.ROOT)),
                               "tables": args.get("tables", ["code", "content"])})
        return json.dumps(res, ensure_ascii=False)
    raise ValueError(f"unknown tool {name}")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        try:
            msg = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send({"error": "bad json"})
        method = msg.get("method", "")
        mid = msg.get("id", 1)
        if method == "initialize":
            resp = {"protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "open-creator-local-mcp", "version": "1.0.0"},
                    "capabilities": {"tools": {}}}
        elif method == "tools/list":
            resp = {"tools": [{"name": k, **v} for k, v in TOOLS.items()]}
        elif method == "tools/call":
            p = msg.get("params", {})
            try:
                text = call_tool(p.get("name", ""), p.get("arguments", {}))
                resp = {"content": [{"type": "text", "text": text}], "isError": False}
            except Exception as e:  # noqa: BLE001
                resp = {"content": [{"type": "text", "text": f"ERROR: {e}"}], "isError": True}
        else:
            resp = {"error": f"unsupported method {method}"}
        self._send({"jsonrpc": "2.0", "id": mid, "result": resp})

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/health"):
            self._send({"ok": True, "local": True, "tools": list(TOOLS)})
        else:
            self._send({"error": "use POST (JSON-RPC)"})

    def _send(self, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("[mcp-8001] " + fmt % args + "\n")


def main() -> None:
    srv = ThreadingHTTPServer((C.HOST, C.MCP_PORT), Handler)
    print(f"MCP (search_code/list_indexed_files/reindex) on http://{C.HOST}:{C.MCP_PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
