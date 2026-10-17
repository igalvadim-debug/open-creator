"""Local indexing, MCP dispatch, AST mapping and stack management unit tests."""
import importlib.util
import io
import json
import os
import signal
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'local-stack'))
from lancedb_mcp import db_http, server_local
from RepoMapper import http_repomapper
import check_local
import config
import setup_models
import start as stack_start


class StackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for patcher in [patch.object(db_http, 'CACHE_FILE', self.root / 'cache.json'),
                        patch.object(db_http, 'db', side_effect=AssertionError('unexpected LanceDB access')),
                        patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network access')),
                        patch('sys.stdout', new_callable=io.StringIO)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_configuration_defaults_are_local_and_environment_overrides_remain_local(self):
        spec = importlib.util.spec_from_file_location('test_local_config', REPO / 'local-stack/config.py')
        for values, llm_port, dimension in [({}, 8484, 768), ({'LOCAL_LLM_PORT': '9000', 'LOCAL_EMBED_MODEL': 'bge-m3-Q8_0.gguf'}, 9000, 1024)]:
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                cfg = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cfg)
                self.assertEqual(cfg.LLM_BASE_URL, f'http://127.0.0.1:{llm_port}/v1')
                self.assertEqual(cfg.EMBED_DIM, dimension)
                self.assertFalse(cfg.ALLOW_FREE_TIER)
                self.assertEqual(cfg.INDEX_BATCH_SIZE, 8)
                for key in ['MODELS_DIR', 'BIN_DIR', 'LOGS_DIR', 'OUTPUT_DIR', 'LANCEDB_DIR']:
                    setattr(cfg, key, self.root / key)
                cfg.ensure_dirs()
                self.assertTrue(all(getattr(cfg, key).is_dir() for key in ['MODELS_DIR', 'BIN_DIR', 'LOGS_DIR', 'OUTPUT_DIR', 'LANCEDB_DIR']))

    def test_chunks_handle_empty_input_and_thirty_line_boundary(self):
        self.assertEqual(db_http.chunk_lines(''), [])
        lines = [str(i) for i in range(31)]
        self.assertEqual(db_http.chunk_lines('\n'.join(lines)), ['\n'.join(lines[:30]), '30'])
        self.assertEqual(db_http.chunk_lines('one\ntwo', size=1), ['one', 'two'])

    def test_file_scanning_excludes_generated_directories_and_matches_uppercase_extensions(self):
        for name in ['src/a.PY', 'node_modules/ignored.py', '.git/ignored.py', 'dist/ignored.py', 'src/ignored.bin']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.assertEqual(list(db_http.iter_files(self.root, {'.py'})), [self.root / 'src/a.PY'])

    def test_corrupt_cache_is_ignored(self):
        db_http.CACHE_FILE.write_text('{broken')
        self.assertEqual(db_http._load_cache(), {})

    def test_indexing_chunks_batches_and_skips_unchanged_content(self):
        source = self.root / 'large.py'
        source.write_text('\n'.join(str(i) for i in range(241)), encoding='utf-8')
        database = MagicMock()
        database.table_names.return_value = []
        with patch.object(db_http, 'db', return_value=database), \
                patch.object(db_http.llama_client, 'embed_batched', side_effect=lambda base, model, texts, **kw: [[1.0] for _ in texts]) as embed:
            self.assertEqual(db_http.index_table(self.root, 'code', {'.py'}), {'files_scanned': 1, 'chunks_pending': 9, 'indexed_chunks': 9})
            self.assertEqual([len(c.args[2]) for c in embed.call_args_list], [8, 1])
            rows = database.create_table.call_args.args[1]
            self.assertEqual(rows[0]['path'], 'large.py#L0')
            self.assertEqual(rows[-1]['path'], 'large.py#L240')
            self.assertEqual(rows[-1]['text'], '240')
            embed.reset_mock()
            self.assertEqual(db_http.index_table(self.root, 'code', {'.py'})['indexed_chunks'], 0)
            previous = source.stat().st_mtime
            os.utime(source, (previous + 10, previous + 10))
            self.assertEqual(db_http.index_table(self.root, 'code', {'.py'})['indexed_chunks'], 0)
            embed.assert_not_called()
            self.assertEqual(db_http._load_cache()['code:large.py']['mtime'], source.stat().st_mtime)

    def test_incremental_update_preserves_other_files_rows(self):
        # SQLite evaluates the same SQL deletion predicate accepted by LanceDB.
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.execute('CREATE TABLE chunks (path TEXT, text TEXT)')
        connection.executemany('INSERT INTO chunks VALUES (?, ?)', [('changed.py#L0', 'old'), ('unchanged.py#L0', 'keep')])
        source = self.root / 'changed.py'
        source.write_text('new', encoding='utf-8')
        database = MagicMock()
        database.table_names.return_value = ['code']
        table = database.open_table.return_value
        table.delete.side_effect = lambda predicate: connection.execute('DELETE FROM chunks WHERE ' + predicate)
        table.add.side_effect = lambda rows: connection.executemany('INSERT INTO chunks VALUES (?, ?)', [(r['path'], r['text']) for r in rows])
        with patch.object(db_http, 'db', return_value=database), patch.object(db_http.llama_client, 'embed_batched', return_value=[[1.0]]):
            db_http.index_table(self.root, 'code', {'.py'})
        self.assertEqual(connection.execute('SELECT text FROM chunks WHERE path = ?', ('unchanged.py#L0',)).fetchall(), [('keep',)])
        self.assertEqual(connection.execute('SELECT text FROM chunks WHERE path = ?', ('changed.py#L0',)).fetchall(), [('new',)])

    def test_failed_embedding_does_not_mark_file_as_indexed(self):
        (self.root / 'a.py').write_text('print(1)')
        with patch.object(db_http, 'db', return_value=MagicMock()), \
                patch.object(db_http.llama_client, 'embed_batched', side_effect=OSError('embedding unavailable')), self.assertRaises(OSError):
            db_http.index_table(self.root, 'code', {'.py'})
        self.assertFalse(db_http.CACHE_FILE.exists())

    def test_search_maps_distances_and_file_listing_deduplicates_chunks(self):
        database = MagicMock()
        table = database.open_table.return_value
        table.search.return_value.limit.return_value.to_list.return_value = [{'path': 'a.py#L0', 'text': 'hit', '_distance': 0.25}]
        table.to_list.return_value = [{'path': 'b.py#L0'}, {'path': 'a.py#L0'}, {'path': 'a.py#L30'}]
        with patch.object(db_http, 'db', return_value=database), patch.object(db_http.llama_client, 'embed', return_value=[[1.0]]) as embed:
            self.assertEqual(db_http.search('code', 'query', k=3), [{'path': 'a.py#L0', 'text': 'hit', '_score': 0.25}])
            table.search.assert_called_once_with([1.0])
            table.search.return_value.limit.assert_called_once_with(3)
            embed.assert_called_once_with(config.EMBED_BASE_URL, config.EMBED_MODEL, ['query'])
            self.assertEqual(db_http.list_files('code'), ['a.py', 'b.py'])
        with patch.object(db_http, 'db', side_effect=RuntimeError('missing table')):
            self.assertEqual(db_http.list_files('code'), [])

    def test_python_mapper_reports_top_level_signatures_and_ignores_invalid_source(self):
        source = self.root / 'a.py'
        source.write_text('async def fetch(url):\n    pass\nclass Client(Base):\n    def get(self): pass\n', encoding='utf-8')
        self.assertEqual(http_repomapper.map_python(source), ['def fetch(url)', 'class Client(Base) {get}'])
        source.write_text('def broken(')
        self.assertEqual(http_repomapper.map_python(source), [])

    def test_repository_map_includes_supported_signatures_and_skips_dependencies(self):
        (self.root / 'a.ts').write_text('export async function fetch() {}\nexport interface Item {}\n')
        (self.root / 'node_modules').mkdir()
        (self.root / 'node_modules/ignored.py').write_text('def ignored(): pass')
        result = http_repomapper.build_map(self.root)
        self.assertEqual(result['files'], 1)
        self.assertEqual(result['map'], {'a.ts': ['export async function fetch() {}', 'export interface Item {}']})

    def test_mcp_tools_apply_defaults_and_forward_explicit_arguments(self):
        with patch.object(server_local, '_rpc', return_value={'results': ['hit']}) as rpc:
            self.assertEqual(json.loads(server_local.call_tool('search_code', {'query': 'text'})), {'results': ['hit']})
            rpc.assert_called_once_with('search', {'table': 'code', 'query': 'text', 'k': 8})
            server_local.call_tool('reindex', {'root': '/project', 'tables': ['content']})
            rpc.assert_called_with('reindex', {'root': '/project', 'tables': ['content']})
        with self.assertRaisesRegex(ValueError, 'unknown tool'):
            server_local.call_tool('missing', {})

    def test_mcp_handler_wraps_tool_errors_as_json_rpc_results(self):
        for method in ['initialize', 'tools/list', 'tools/call']:
            with self.subTest(method=method):
                message = json.dumps({'id': 42, 'method': method, 'params': {'name': 'missing'}}).encode()
                handler = object.__new__(server_local.Handler)
                handler.headers = {'Content-Length': str(len(message))}
                handler.rfile = io.BytesIO(message)
                handler._send = MagicMock()
                handler.do_POST()
                result = handler._send.call_args.args[0]
                self.assertEqual(result['id'], 42)
                self.assertEqual(result['jsonrpc'], '2.0')
                if method == 'initialize':
                    self.assertIn('tools', result['result']['capabilities'])
                elif method == 'tools/list':
                    self.assertEqual({tool['name'] for tool in result['result']['tools']}, set(server_local.TOOLS))
                else:
                    self.assertTrue(result['result']['isError'])

    def test_model_picker_prefers_configured_model_and_excludes_vision_projection(self):
        with patch.object(stack_start.C, 'MODELS_DIR', self.root):
            (self.root / 'mmproj.gguf').touch()
            with self.assertRaises(SystemExit):
                stack_start.pick_model()
            fallback = self.root / 'fallback.gguf'
            fallback.touch()
            self.assertEqual(stack_start.pick_model(), str(fallback))
            preferred = self.root / stack_start.C.DEFAULT_LLM_MODEL
            preferred.touch()
            self.assertEqual(stack_start.pick_model(), str(preferred))
            with self.assertRaises(SystemExit):
                stack_start.pick_embed_model()
            embedding = self.root / stack_start.C.EMBED_MODEL_FALLBACK
            embedding.touch()
            self.assertEqual(stack_start.pick_embed_model(), str(embedding))

    def test_stop_handles_missing_stale_and_invalid_pids(self):
        pidfile = self.root / '.pids'
        with patch.object(stack_start, 'PIDFILE', pidfile), patch.object(stack_start.os, 'kill', side_effect=[None, ProcessLookupError]) as kill:
            stack_start.stop()
            kill.assert_not_called()
            pidfile.write_text('123\ninvalid\n456')
            stack_start.stop()
        self.assertEqual([c.args for c in kill.call_args_list], [(123, signal.SIGTERM), (456, signal.SIGTERM)])
        self.assertFalse(pidfile.exists())

    def test_model_download_skips_existing_files_and_renames_complete_partial(self):
        with patch.object(setup_models.C, 'MODELS_DIR', self.root), patch('urllib.request.urlopen') as opened:
            response = opened.return_value.__enter__.return_value
            response.read.side_effect = [b'model', b'']
            result = setup_models.download('owner/repo', 'resolve/main/model.gguf')
            self.assertEqual(result.read_bytes(), b'model')
            self.assertFalse((self.root / 'model.gguf.part').exists())
            opened.assert_called_once_with('https://huggingface.co/owner/repo/resolve/main/model.gguf')
            setup_models.download('owner/repo', 'resolve/main/model.gguf')
            self.assertEqual(opened.call_count, 1)

    def test_health_check_returns_failure_for_required_services_but_allows_optional_comfyui(self):
        values = [{'data': []}] * 5 + [None, None]
        with patch.object(check_local, 'http_get', side_effect=values), \
                patch.object(check_local.llama_client, 'chat', return_value='pong'), \
                patch.object(check_local.llama_client, 'embed', return_value=[[0.1]]), patch.object(check_local.C, 'ALLOW_FREE_TIER', False):
            self.assertEqual(check_local.main(), 0)
        with patch.object(check_local, 'http_get', return_value=None), patch.object(check_local.C, 'ALLOW_FREE_TIER', False):
            self.assertEqual(check_local.main(), 1)
