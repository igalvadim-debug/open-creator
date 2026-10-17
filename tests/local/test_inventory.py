"""Offline ComfyUI catalogs and imported Windows inventories."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'cwbuilder-docs'))
import cw_local
import parse_external_inventory as external
import parse_inventory as inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.local = self.root / 'ComfyUI-local'
        self.catalog = self.root / 'catalog.json'
        for module in [cw_local, external, inventory]:
            patcher = patch.object(module, 'LOCAL', self.local)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in [patch.object(cw_local, 'HERE', self.root), patch.object(cw_local, 'CATALOG', self.catalog),
                        patch.object(external, 'CATALOG', self.catalog), patch.object(inventory, 'CW_ROOT', self.root),
                        patch('sys.stdout', new_callable=io.StringIO)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_setup_is_idempotent_and_preserves_existing_catalog(self):
        cw_local.cmd_setup()
        self.assertTrue(all((self.local / sub).is_dir() for sub in cw_local.SUBDIRS))
        self.assertEqual(json.loads(self.catalog.read_text())['models'], [])
        self.catalog.write_text('{"models": [{"name": "kept"}]}')
        cw_local.cmd_setup()
        self.assertEqual(cw_local.load_catalog()['models'], [{'name': 'kept'}])

    def test_missing_catalog_produces_actionable_error(self):
        with self.assertRaisesRegex(SystemExit, 'parse_inventory.py'):
            cw_local.load_catalog()

    def test_scanner_includes_nested_models_and_ignores_non_model_files(self):
        models = self.local / 'lora' / 'nested'
        models.mkdir(parents=True)
        (models / 'style.SAFETENSORS').write_bytes(b'weight')
        (models / 'readme.txt').write_text('ignore')
        (self.root / 'workflow_test.json').write_text('{}')
        result = inventory.scan()
        self.assertEqual(result['total_models'], 1)
        self.assertEqual(result['by_category'], {'lora': 1})
        self.assertEqual(result['models'][0]['path'], 'lora/nested/style.SAFETENSORS')
        self.assertEqual(result['workflows'], ['workflow_test.json'])

    def test_scanner_handles_empty_root(self):
        self.assertEqual(inventory.scan()['models'], [])

    def test_windows_paths_and_triggers_are_normalized_without_copying_weights(self):
        entries = external.load_entries('\n'.join([
            r'C:\models\loras\style.safetensors -> Trigger: cinematic / noir',
            r'C:\models\loras\style.safetensors -> Trigger: duplicate',
            r'D:\ComfyUI\models\vae\video.gguf',
            r'D:\ComfyUI\models\vae\readme.txt', 'not a model'
        ]))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0], {'name': 'style.safetensors', 'category': 'lora', 'path': 'loras/style.safetensors',
                                     'size_mb': 0.0, 'trigger': 'cinematic / noir', 'source_root': 'C:', 'present': False})
        self.assertEqual(entries[1]['path'], 'vae/video.gguf')
        self.assertFalse(self.local.exists())

    def test_no_trigger_markers_and_category_aliases(self):
        for marker in ['-', '–', '(kein Trigger)', 'null']:
            with self.subTest(marker=marker):
                self.assertEqual(external.parse_line('C:/models/loras/a.gguf → Trigger: ' + marker), ('C:/models/loras/a.gguf', ''))
        for folder, category in [('qwen-tts', 'tts'), ('RMBG', 'background_removal'), ('diffusion_models', 'diffusion_model')]:
            with self.subTest(folder=folder):
                self.assertEqual(external.category_from_path('D:/ComfyUI/models/' + folder + '/a.gguf'), category)
        self.assertEqual(external.category_from_path('D:/unknown/a.gguf'), 'misc')
        self.assertEqual(external.rel_name('D:/unknown/a.gguf'), 'unknown/a.gguf')

    def test_external_import_dry_run_does_not_modify_catalog(self):
        source = self.root / 'inventory.txt'
        source.write_text('C:/models/vae/a.gguf', encoding='utf-8')
        external.main(['parse_external_inventory.py', str(source)])
        self.assertFalse(self.catalog.exists())

    def test_external_import_is_idempotent_and_refreshes_presence_flags(self):
        source = self.root / 'inventory.txt'
        source.write_text('C:/models/vae/a.gguf', encoding='utf-8')
        (self.local / 'vae').mkdir(parents=True)
        (self.local / 'vae' / 'a.gguf').touch()
        external.main(['parse_external_inventory.py', str(source), '--apply'])
        external.main(['parse_external_inventory.py', str(source), '--apply'])
        catalog = json.loads(self.catalog.read_text(encoding='utf-8'))
        self.assertEqual(catalog['total_models'], 1)
        self.assertEqual(catalog['by_category'], {'vae': 1})
        self.assertTrue(catalog['models'][0]['present'])

    def test_catalog_search_matches_model_name_and_category_case_insensitively(self):
        self.catalog.write_text(json.dumps({'models': [{'name': 'Forest.gguf', 'category': 'lora'},
                                                       {'name': 'Base.gguf', 'category': 'checkpoints'}]}))
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            cw_local.cmd_find('FOREST')
        self.assertIn('Forest.gguf', out.getvalue())
        self.assertNotIn('Base.gguf', out.getvalue())
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            cw_local.cmd_find('CHECKPOINTS')
        self.assertIn('Base.gguf', out.getvalue())
