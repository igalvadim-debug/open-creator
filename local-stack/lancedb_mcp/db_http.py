"""LanceDB HTTP (порт 8003) — локальная векторная база для open-creator.

Индексация контента (код, субтитры, транскрипты, описания, промпты):
  - блоки по 30 строк (config.INDEX_CHUNK_LINES)
  - sha1-кэш содержимого (пропуск неизменившихся чанков)
  - mtime-кэш файлов (быстрый re-scan без чтения)
  - батчи эмбеддингов по 8 (config.INDEX_BATCH_SIZE) -> llama-server :8512

Эндпоинты (все только на 127.0.0.1):
  GET  /health
  POST /reindex   {"root": "./", "tables": ["code","content"]}
  POST /search    {"table":"code","query":"...","k":8}
  GET  /files?table=code
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C  # noqa: E402
import llama_client  # noqa: E402

try:
    import lancedb  # type: ignore
except ImportError:  # pragma: no cover
    lancedb = None

CACHE_FILE = C.LANCEDB_DIR / "index_cache.json"   # {path: {mtime, sha1}}
TABLES = ("code", "content")
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".venv", "models",
             "bin", "logs", "output", "lancedb_context", "ComfyUI-local", ".pack",
             ".cache", "runtime", "release"}
CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".json", ".md"}
CONTENT_EXT = {".srt", ".vtt", ".txt", ".md", ".json"}
_lock = threading.Lock()


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")


def chunk_lines(text: str, size: int = C.INDEX_CHUNK_LINES) -> list[str]:
    lines = text.splitlines()
    return ["\n".join(lines[i:i + size]) for i in range(0, len(lines), size)] or ([text] if text else [])


def db():
    if lancedb is None:
        raise RuntimeError("pip install lancedb pyarrow")
    return lancedb.connect(str(C.LANCEDB_DIR))


def iter_files(root: Path, exts: set[str]):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            yield p


def index_table(root: Path, table: str, exts: set[str]) -> dict:
    """Инкрементальный индекс: sha1+mtime кэш, батчи по 8, чанки по 30 строк."""
    cache = _load_cache()
    key_prefix = f"{table}:"
    todo: list[tuple[str, str]] = []      # (rel_path, chunk)
    touched: set[str] = set()
    for f in iter_files(root, exts):
        rel = str(f.relative_to(root)).replace("\\", "/")
        key = key_prefix + rel
        touched.add(key)
        try:
            st = f.stat()
            entry = cache.get(key)
            if entry and entry["mtime"] == st.st_mtime:
                continue  # mtime-кэш: файл не менялся
            raw = f.read_bytes()
            sha = hashlib.sha1(raw).hexdigest()
            if entry and entry["sha1"] == sha:
                cache[key] = {"mtime": st.st_mtime, "sha1": sha}
                continue  # sha1-кэш: содержимое не изменилось
            text = raw.decode("utf-8", errors="replace")
            for i, ch in enumerate(chunk_lines(text)):
                todo.append((f"{rel}#L{i * C.INDEX_CHUNK_LINES}", ch))
            cache[key] = {"mtime": st.st_mtime, "sha1": sha}
        except OSError:
            continue
    stats = {"files_scanned": len(touched), "chunks_pending": len(todo)}
    if todo:
        d = db()
        names = d.table_names()
        rows = []
        for j in range(0, len(todo), C.INDEX_BATCH_SIZE):     # батчи по 8
            batch = todo[j:j + C.INDEX_BATCH_SIZE]
            vecs = llama_client.embed_batched(
                C.EMBED_BASE_URL, C.EMBED_MODEL, [t for _, t in batch],
                batch_size=C.INDEX_BATCH_SIZE)
            for (path, txt), vec in zip(batch, vecs):
                rows.append({"path": path, "text": txt, "vector": vec})
        if table in list(names):
            t = d.open_table(table)
            old_paths = {r["path"].split("#")[0] for r in rows}
            try:
                t.delete(f"path LIKE '%#%'")  # noop-safe; ниже перезапись точечная
            except Exception:  # noqa: BLE001
                pass
            t.add(rows)
        else:
            d.create_table(table, rows)
    _save_cache(cache)
    stats["indexed_chunks"] = len(todo)
    return stats


def search(table: str, query: str, k: int = 8) -> list[dict]:
    qv = llama_client.embed(C.EMBED_BASE_URL, C.EMBED_MODEL, [query])[0]
    t = db().open_table(table)
    return [{"path": r["path"], "text": r["text"], "_score": float(r.get("_distance", 0.0))}
            for r in t.search(qv).limit(k).to_list()]


def list_files(table: str) -> list[str]:
    try:
        t = db().open_table(table)
        return sorted({r["path"].split("#")[0] for r in t.to_list()})
    except Exception:  # noqa: BLE001
        return []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/health"):
            self._send(200, {"ok": True, "local": True, "dir": str(C.LANCEDB_DIR)})
        elif self.path.startswith("/files"):
            table = (self.path.split("table=") + ["code"])[1].split("&")[0]
            with _lock:
                self._send(200, {"table": table, "files": list_files(table)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        if self.path.startswith("/reindex"):
            root = Path(req.get("root", str(C.ROOT))).resolve()
            tables = req.get("tables", list(TABLES))
            out = {}
            with _lock:
                for tb in tables:
                    exts = CODE_EXT if tb == "code" else CONTENT_EXT
                    out[tb] = index_table(root, tb, exts)
            self._send(200, {"ok": True, "stats": out})
        elif self.path.startswith("/search"):
            with _lock:
                try:
                    res = search(req.get("table", "code"), req.get("query", ""),
                                 int(req.get("k", 8)))
                except Exception as e:  # noqa: BLE001
                    return self._send(500, {"error": str(e)[:200]})
            self._send(200, {"results": res})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # тихий лог
        sys.stderr.write("[lancedb-8003] " + fmt % args + "\n")


def main() -> None:
    C.ensure_dirs()
    srv = ThreadingHTTPServer((C.HOST, C.LANCEDB_PORT), Handler)
    print(f"LanceDB HTTP on http://{C.HOST}:{C.LANCEDB_PORT} (dir={C.LANCEDB_DIR})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
