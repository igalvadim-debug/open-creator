"""ComfyUI workflow generation and polling, using in-memory HTTP responses."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import image_gen, video_gen
import cw_prompt_enhance


def response(body):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = body if isinstance(body, bytes) else json.dumps(body).encode()
    return result


class GenerationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workflow = self.root / 'workflow.json'
        self.original = {'nodes': [
            {'inputs': {'text': 'PROMPT_HERE', 'width': 64, 'height': 64, 'seed': 99, 'ckpt_name': 'old'}},
            {'inputs': {'text': 'negative prompt', 'other': True}}, {'class_type': 'SaveImage'}
        ], 'defaults': {'keep': True}}
        self.workflow.write_text(json.dumps(self.original), encoding='utf-8')
        patcher = patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network access'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_image_workflow_replaces_positive_prompt_dimensions_and_zero_seed(self):
        before = self.workflow.read_bytes()
        result = image_gen.build_workflow('forest', width=768, height=512, seed=0, workflow_path=self.workflow)
        self.assertEqual(result['nodes'][0]['inputs'], {'text': 'forest', 'width': 768, 'height': 512, 'seed': 0, 'ckpt_name': 'old'})
        self.assertEqual(result['nodes'][1], self.original['nodes'][1])
        self.assertEqual(self.workflow.read_bytes(), before)

    def test_video_workflow_sets_model_and_defaults_without_mutating_template(self):
        with patch.object(video_gen, 'workflow_path', return_value=self.workflow):
            result = video_gen.build_workflow('motion', width=1280, height=720, seed=0, model='local.gguf')
        self.assertEqual(result['nodes'][0]['inputs'], {'text': 'motion', 'width': 1280, 'height': 720, 'seed': 0, 'ckpt_name': 'local.gguf'})
        self.assertEqual(result['defaults'], {'keep': True, 'width': 1280, 'height': 720, 'batch_size': 1})
        self.assertEqual(json.loads(self.workflow.read_text()), self.original)

    def test_automatic_seed_is_bounded(self):
        with patch.object(image_gen.time, 'time', return_value=2 ** 31 + 17):
            wf = image_gen.build_workflow('test', workflow_path=self.workflow)
        self.assertEqual(wf['nodes'][0]['inputs']['seed'], 17)

    def test_workflow_alias_explicit_path_and_missing_file(self):
        with patch.object(video_gen.C, 'CW_ROOT', self.root), patch.object(video_gen.C, 'CW_WORKFLOWS', {'minimax_4step': 'workflow.json'}):
            self.assertEqual(video_gen.workflow_path(), self.workflow)
            self.assertEqual(video_gen.workflow_path(str(self.workflow)), self.workflow)
            with self.assertRaises(FileNotFoundError):
                video_gen.workflow_path('missing.json')

    def test_all_configured_workflow_aliases_resolve_to_shipped_files(self):
        for alias in video_gen.C.CW_WORKFLOWS:
            with self.subTest(alias=alias):
                self.assertTrue(video_gen.workflow_path(alias).is_file())

    def test_catalog_filtering_and_case_insensitive_lora_triggers(self):
        catalog = self.root / 'catalog.json'
        models = [{'name': 'style', 'category': 'lora', 'trigger': 'Forest'},
                  {'name': 'untriggered', 'category': 'lora'}, {'name': 'base', 'category': 'checkpoints'}]
        catalog.write_text(json.dumps({'models': models}), encoding='utf-8')
        with patch.object(image_gen.C, 'CW_CATALOG', catalog):
            self.assertEqual(image_gen.catalog_models(), models)
            self.assertEqual(image_gen.catalog_models('checkpoints'), [models[2]])
            self.assertEqual(image_gen.loras_for_prompt('A FOREST scene'), [models[0]])
            catalog.unlink()
            self.assertEqual(image_gen.catalog_models(), [])

    def test_prompt_enhancement_uses_local_model_and_strips_wrapping_quotes(self):
        with patch.object(cw_prompt_enhance.llama_client, 'chat', return_value='  "detailed prompt"  ') as chat:
            self.assertEqual(cw_prompt_enhance.enhance('forest', lang='de', model='custom'), 'detailed prompt')
        self.assertEqual(chat.call_args.args[0:2], (cw_prompt_enhance.C.LLM_BASE_URL, 'custom'))
        self.assertIn('in de', chat.call_args.args[2][0]['content'])
        self.assertEqual(chat.call_args.args[2][1], {'role': 'user', 'content': 'forest'})
        with patch.object(cw_prompt_enhance, 'enhance', side_effect=OSError('offline')):
            self.assertEqual(image_gen.enhance('original'), 'original')

    def test_generation_posts_polls_and_downloads_local_artifacts(self):
        for module, output_type in [(image_gen, 'images'), (video_gen, 'videos')]:
            with self.subTest(module=module.__name__), \
                    patch.object(module, 'build_workflow', return_value=copy.deepcopy(self.original)) as build, \
                    patch.object(module.time, 'sleep') as sleep, \
                    patch.object(cw_prompt_enhance, 'enhance', return_value='enhanced') as enhance, \
                    patch('urllib.request.urlopen', side_effect=[response({'prompt_id': 'task'}), response({}),
                          response({'task': {'outputs': {'save': {output_type: [{'filename': 'result.bin', 'subfolder': 'run'}]}}}}),
                          response(b'synthetic media')]) as opened:
                out = self.root / module.__name__ / 'result.bin'
                self.assertEqual(module.generate('forest', out), out)
                self.assertEqual(out.read_bytes(), b'synthetic media')
                enhance.assert_called_once_with('forest')
                self.assertEqual(build.call_args.args[0], 'enhanced')
                request = opened.call_args_list[0].args[0]
                self.assertEqual(request.full_url, module.SERVER + '/prompt')
                payload = json.loads(request.data)
                self.assertEqual(payload['prompt'], self.original)
                self.assertEqual(len(payload['client_id']), 12)
                self.assertEqual(opened.call_args_list[1].args[0], module.SERVER + '/history/task')
                self.assertEqual(opened.call_args_list[-1].args[0], module.SERVER + '/view?filename=result.bin&subfolder=run&type=output')
                sleep.assert_called_once()

    def test_generation_supports_gif_outputs_without_enhancement(self):
        for module in [image_gen, video_gen]:
            with self.subTest(module=module.__name__), patch.object(module, 'build_workflow', return_value={}), \
                    patch.object(cw_prompt_enhance, 'enhance') as enhance, \
                    patch('urllib.request.urlopen', side_effect=[response({'prompt_id': 'task'}),
                          response({'task': {'outputs': {'save': {'gifs': [{'filename': 'out.gif'}]}}}}), response(b'GIF89a')]):
                out = self.root / 'out.gif'
                module.generate('original', out, enhance_prompt=False)
                self.assertEqual(out.read_bytes(), b'GIF89a')
                enhance.assert_not_called()

    def test_generation_empty_output_and_timeout_do_not_create_artifact(self):
        for module in [image_gen, video_gen]:
            out = self.root / 'missing.bin'
            with self.subTest(module=module.__name__), patch.object(module, 'build_workflow', return_value={}), \
                    patch('urllib.request.urlopen', side_effect=[response({'prompt_id': 'task'}), response({'task': {'outputs': {}}})]), \
                    self.assertRaises(RuntimeError):
                module.generate('test', out, enhance_prompt=False)
            with patch.object(module, 'build_workflow', return_value={}), \
                    patch('urllib.request.urlopen', return_value=response({'prompt_id': 'task'})), \
                    patch.object(module.time, 'time', side_effect=[0, 1]), self.assertRaises(TimeoutError):
                module.generate('test', out, enhance_prompt=False, timeout=0)
            self.assertFalse(out.exists())

    def test_external_server_is_rejected_before_workflow_or_network_access(self):
        for module in [image_gen, video_gen]:
            with self.subTest(module=module.__name__), patch.object(module, 'SERVER', 'https://external.example.test'), \
                    patch.object(module, 'build_workflow') as build, self.assertRaisesRegex(RuntimeError, 'POLICY'):
                module.generate('test', self.root / 'out.bin')
            build.assert_not_called()
