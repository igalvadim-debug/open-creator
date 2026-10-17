"""Local AI clients: no model weights, optional packages or live servers required."""
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import embedding_client, llm_client, translation
import llama_client


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network access'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_local_hosts_and_external_hosts(self):
        for url in ['http://127.0.0.1:8484/v1', 'http://localhost/v1', 'http://[::1]/v1', 'http://0.0.0.0']:
            with self.subTest(url=url):
                llama_client.assert_local(url)
        with self.assertRaisesRegex(RuntimeError, 'POLICY'):
            llama_client.assert_local('https://cloud.example.test/v1')

    def test_local_host_text_cannot_disguise_an_external_destination(self):
        for url in ['http://localhost.example.test/v1', 'http://localhost@external.example.test/v1',
                    'https://external.example.test/127.0.0.1', 'https://external.example.test/?host=localhost']:
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, 'POLICY'):
                llama_client.assert_local(url)

    def test_post_encodes_json_and_respects_timeout(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'
        with patch('urllib.request.urlopen', return_value=response) as opened:
            self.assertEqual(llama_client._post('http://localhost/v1/chat/completions', {'text': 'Привет'}, timeout=7), {'ok': True})
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {'text': 'Привет'})
        self.assertEqual(opened.call_args.kwargs, {'timeout': 7})

    def test_chat_builds_non_streaming_completion(self):
        messages = [{'role': 'user', 'content': 'hello'}]
        with patch.object(llama_client, '_post', return_value={'choices': [{'message': {'content': 'answer'}}]}) as post:
            self.assertEqual(llama_client.chat('http://localhost/v1///', 'model', messages, temperature=0.1, max_tokens=9, timeout=3), 'answer')
        post.assert_called_once_with('http://localhost/v1/chat/completions', {
            'model': 'model', 'messages': messages, 'temperature': 0.1, 'max_tokens': 9, 'stream': False
        }, timeout=3)

    def test_embedding_results_are_sorted_by_input_index(self):
        with patch.object(llama_client, '_post', return_value={'data': [
            {'index': 1, 'embedding': [2.0]}, {'index': 0, 'embedding': [1.0]}
        ]}) as post:
            self.assertEqual(llama_client.embed('http://localhost/v1/', 'embed', ['a', 'b'], timeout=4), [[1.0], [2.0]])
        post.assert_called_once_with('http://localhost/v1/embeddings', {'model': 'embed', 'input': ['a', 'b']}, timeout=4)

    def test_embedding_batches_preserve_order_and_flush_remainder(self):
        with patch.object(llama_client, 'embed', side_effect=lambda base, model, batch, **kw: [[int(x)] for x in batch]) as embed:
            self.assertEqual(llama_client.embed_batched('http://localhost/v1', 'embed', (str(i) for i in range(5)), batch_size=2, timeout=6), [[0], [1], [2], [3], [4]])
        self.assertEqual([call.args[2] for call in embed.call_args_list], [['0', '1'], ['2', '3'], ['4']])
        self.assertTrue(all(call.kwargs == {'timeout': 6} for call in embed.call_args_list))

    def test_empty_embedding_batch_does_not_contact_server(self):
        with patch.object(llama_client, 'embed') as embed:
            self.assertEqual(llama_client.embed_batched('http://localhost/v1', 'embed', []), [])
        embed.assert_not_called()

    def test_wait_ready_retries_connection_errors_then_returns_true(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch('urllib.request.urlopen', side_effect=[urllib.error.URLError('starting'), response]) as opened, \
                patch.object(llama_client.time, 'time', side_effect=[0, 1, 2]), \
                patch.object(llama_client.time, 'sleep') as sleep:
            self.assertTrue(llama_client.wait_ready('http://localhost/v1/', timeout=5))
        self.assertEqual(opened.call_count, 2)
        opened.assert_called_with('http://localhost/v1/models', timeout=3)
        sleep.assert_called_once_with(1.0)

    def test_wait_ready_timeout_and_external_url_do_not_dispatch(self):
        with patch.object(llama_client.time, 'time', side_effect=[0, 5]):
            self.assertFalse(llama_client.wait_ready('http://localhost/v1', timeout=5))
        with self.assertRaisesRegex(RuntimeError, 'POLICY'):
            llama_client.wait_ready('https://external.example.test/v1', timeout=0)

    def test_llm_wrapper_forwards_custom_model_and_options(self):
        with patch.object(llm_client.LC, 'chat', return_value='answer') as chat:
            self.assertEqual(llm_client.complete('question', system='rules', model='custom', max_tokens=12, temperature=0.8, timeout=2), 'answer')
        chat.assert_called_once_with(llm_client.BASE_URL, 'custom', [
            {'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'question'}
        ], max_tokens=12, temperature=0.8, timeout=2)

    def test_llm_wrapper_defaults_and_missing_system(self):
        with patch.object(llm_client.LC, 'chat', return_value='answer') as chat:
            llm_client.complete('question')
        self.assertEqual(chat.call_args.args[1], llm_client.C.DEFAULT_LLM_MODEL)
        self.assertEqual(chat.call_args.args[2], [{'role': 'user', 'content': 'question'}])

    def test_readiness_reports_errors(self):
        with patch.object(llm_client.LC, 'wait_ready', side_effect=OSError('unavailable')):
            self.assertFalse(llm_client.is_ready(timeout=1))

    def test_readiness_reports_a_normal_timeout_as_not_ready(self):
        with patch.object(llm_client.LC, 'wait_ready', return_value=False) as ready:
            self.assertFalse(llm_client.is_ready(timeout=1))
        ready.assert_called_once_with(llm_client.BASE_URL, timeout=1)

    def test_embedding_wrapper_materializes_iterables_and_uses_configured_batch_size(self):
        with patch.object(embedding_client.LC, 'embed_batched', return_value=[[1]]) as batched:
            self.assertEqual(embedding_client.embed_many(x for x in ['a', 'b']), [[1]])
        batched.assert_called_once_with(embedding_client.BASE_URL, embedding_client.C.EMBED_MODEL, ['a', 'b'], batch_size=embedding_client.C.INDEX_BATCH_SIZE)
        with patch.object(embedding_client.LC, 'embed', return_value=[]) as embed:
            self.assertEqual(embedding_client.embed([], timeout=5), [])
        embed.assert_called_once_with(embedding_client.BASE_URL, embedding_client.C.EMBED_MODEL, [], timeout=5)

    def test_free_tier_is_explicitly_disabled_and_never_silently_contacts_cloud(self):
        with patch.object(embedding_client.C, 'ALLOW_FREE_TIER', False), self.assertRaisesRegex(RuntimeError, 'ALLOW_FREE_TIER=0'):
            embedding_client.free_tier_embed_unsafe(['secret'])
        with patch.object(embedding_client.C, 'ALLOW_FREE_TIER', True), self.assertRaises(NotImplementedError):
            embedding_client.free_tier_embed_unsafe(['secret'])


class TranslationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        prompt = Path(temp.name) / 'translation.txt'
        prompt.write_text('Translate {src_name} to {dst_name}', encoding='utf-8')
        patcher = patch.object(translation, 'PROMPT_FILE', prompt)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.prompt = prompt

    def test_prompt_file_and_missing_file_fallback(self):
        self.assertEqual(translation.load_prompt_template(), 'Translate {src_name} to {dst_name}')
        self.prompt.unlink()
        self.assertIn('{dst_name}', translation.load_prompt_template())

    def test_translation_language_names_and_model_override(self):
        with patch.object(translation.llm_client, 'chat', return_value='Hallo') as chat:
            self.assertEqual(translation.translate('Hello', 'en', 'de', model='custom'), 'Hallo')
        chat.assert_called_once_with([{'role': 'system', 'content': 'Translate EN to German'},
                                     {'role': 'user', 'content': 'Hello'}], model='custom', temperature=0.2, max_tokens=4096)

    def test_batches_restart_numbering_and_preserve_missing_translations(self):
        with patch.object(translation.llm_client, 'chat', side_effect=['2) zwei\n1. eins\n99. ignored', 'model omitted numbering']) as chat:
            result = translation.translate_lines(['one', 'two', 'three'], batch=2, dst='de')
        self.assertEqual(result, ['eins', 'zwei', 'three'])
        self.assertEqual([call.args[0][1]['content'] for call in chat.call_args_list], ['1. one\n2. two', '1. three'])
        self.assertEqual(chat.call_args_list[0].args[0][0]['content'], 'Translate source language to German')

    def test_empty_lines_do_not_call_model(self):
        with patch.object(translation.llm_client, 'chat') as chat:
            self.assertEqual(translation.translate_lines([]), [])
        chat.assert_not_called()

    def test_subtitle_translation_preserves_timing_metadata_and_original_input(self):
        segments = [{'start': 1.2, 'end': 3.4, 'text': 'Hello', 'speaker': 'A'}]
        with patch.object(translation, 'translate_lines', return_value=['Hallo']) as translate:
            self.assertEqual(translation.translate_srt(segments, 'en', 'de', model='local'), [
                {'start': 1.2, 'end': 3.4, 'text': 'Hallo', 'text_orig': 'Hello', 'speaker': 'A'}
            ])
        translate.assert_called_once_with(['Hello'], 'en', 'de', model='local')
        self.assertEqual(segments[0]['text'], 'Hello')
