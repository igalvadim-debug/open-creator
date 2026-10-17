"""Agent sandbox and pipeline orchestration without shell or model execution."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents import local_agent
from pipelines import download_translate_dub as dubbing
from pipelines import image_pipeline, video_pipeline


class AgentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'repo'
        self.root.mkdir()
        for patcher in [patch.object(local_agent, '_ROOT', self.root),
                        patch('subprocess.run', side_effect=AssertionError('unexpected shell operation')),
                        patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network access'))]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_parse_action_handles_fences_surrounding_text_and_invalid_json(self):
        for text in ['{"final":"done"}', '```json\n{"final":"done"}\n```', 'Here is the result: {"final":"done"}']:
            with self.subTest(text=text):
                self.assertEqual(local_agent.parse_action(text), {'final': 'done'})
        for text in ['not JSON', '{broken}', '']:
            with self.subTest(text=text):
                self.assertIsNone(local_agent.parse_action(text))

    def test_file_tools_create_parents_and_limit_reads(self):
        result = local_agent.execute('write_file', {'path': 'nested/result.txt', 'content': 'Привет'})
        self.assertIn('nested/result.txt', result)
        self.assertEqual(local_agent.execute('read_file', {'path': 'nested/result.txt'}), 'Привет')
        (self.root / 'large.txt').write_text('x' * 20001)
        self.assertEqual(len(local_agent.execute('read_file', {'path': 'large.txt'})), 20000)

    def test_file_tools_reject_parent_traversal_and_absolute_paths_outside_repository(self):
        for path in ['../outside.txt', str(self.root.parent / 'outside.txt')]:
            for tool in ['read_file', 'write_file']:
                with self.subTest(path=path, tool=tool), self.assertRaises(RuntimeError):
                    local_agent.execute(tool, {'path': path, 'content': 'no'})
        self.assertFalse((self.root.parent / 'outside.txt').exists())

    def test_safe_path_rejects_a_symlink_pointing_outside_repository(self):
        outside = self.root.parent / 'outside'
        outside.mkdir()
        try:
            (self.root / 'escape').symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(RuntimeError):
            local_agent._safe_path('escape/file.txt')

    def test_shell_rejects_network_commands_before_spawning(self):
        for cmd in ['curl localhost', 'wget file', 'python https://external.example.test', 'nc host', 'ssh host']:
            with self.subTest(cmd=cmd):
                self.assertTrue(local_agent.execute('run_shell', {'cmd': cmd}).startswith('REJECTED:'))

    def test_shell_runs_from_repository_and_returns_bounded_stdout_and_stderr(self):
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='out', stderr='err')) as run:
            self.assertEqual(local_agent.execute('run_shell', {'cmd': 'ffmpeg -version'}), 'outerr')
        run.assert_called_once_with('ffmpeg -version', shell=True, capture_output=True, text=True, timeout=600, cwd=str(self.root))
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='x' * 30000, stderr='')):
            self.assertEqual(len(local_agent.execute('run_shell', {'cmd': 'ffmpeg -version'})), 20000)

    def test_mcp_request_uses_local_json_rpc_and_extracts_text(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"result":{"content":[{"text":"found"}]}}'
        with patch('urllib.request.urlopen', return_value=response) as opened:
            self.assertEqual(local_agent.execute('search_code', {'query': 'translation'}), 'found')
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, local_agent.C.MCP_URL)
        self.assertEqual(json.loads(request.data), {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                  'params': {'name': 'search_code', 'arguments': {'query': 'translation'}}})

    def test_agent_observes_tool_result_then_returns_final_answer(self):
        action = json.dumps({'tool': 'read_file', 'args': {'path': 'a.txt'}})
        snapshots = []

        def chat(base, model, messages, **kwargs):
            snapshots.append([dict(message) for message in messages])
            return action if len(snapshots) == 1 else '{"final":"done"}'

        with patch.object(local_agent.LC, 'chat', side_effect=chat), patch.object(local_agent, 'execute', return_value='contents') as execute:
            self.assertEqual(local_agent.run('read file', model='custom'), 'done')
        execute.assert_called_once_with('read_file', {'path': 'a.txt'})
        self.assertEqual(snapshots[1][-2:], [{'role': 'assistant', 'content': action}, {'role': 'user', 'content': 'OBSERVATION:\ncontents'}])

    def test_agent_returns_plain_text_and_respects_step_budget(self):
        with patch.object(local_agent.LC, 'chat', return_value='plain answer'):
            self.assertEqual(local_agent.run('task'), 'plain answer')
        with patch.object(local_agent.LC, 'chat', return_value='{"tool":"unknown"}') as chat:
            self.assertIn('max steps reached', local_agent.run('task', max_steps=2))
            self.assertEqual(chat.call_count, 2)
            chat.reset_mock()
            self.assertIn('max steps reached', local_agent.run('task', max_steps=0))
            chat.assert_not_called()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for patcher in [patch('subprocess.run', side_effect=AssertionError('unexpected process')),
                        patch.object(dubbing.C, 'OUTPUT_DIR', self.root), patch.object(dubbing.C, 'ensure_dirs'),
                        patch('sys.stdout', new_callable=io.StringIO)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_assemble_without_audio_copies_video(self):
        source = self.root / 'video.mp4'
        source.write_bytes(b'synthetic video')
        out = self.root / 'copy.mp4'
        self.assertEqual(dubbing.assemble(source, [], [], out), out)
        self.assertEqual(out.read_bytes(), source.read_bytes())

    def test_assemble_delays_the_dub_inputs_and_preserves_video_stream(self):
        source, first, second, out = [self.root / name for name in ['v.mp4', 'a.wav', 'b.wav', 'out.mp4']]
        with patch('shutil.which', return_value='ffmpeg'), patch('subprocess.run') as run:
            self.assertEqual(dubbing.assemble(source, [first, second], [{'start': 1.25}, {'start': 3}], out), out)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:8], ['ffmpeg', '-y', '-i', str(source), '-i', str(first), '-i', str(second)])
        self.assertIn('0:v', cmd)
        self.assertEqual(cmd[cmd.index('-filter_complex') + 1],
                         '[1:a]adelay=1250|1250[a0];[2:a]adelay=3000|3000[a1];[a0][a1]amix=inputs=2:duration=longest:normalize=0[mix]')

    def test_dubbing_pipeline_preserves_data_flow_and_no_dub_skips_synthesis(self):
        segments = [{'start': 0, 'end': 1, 'text': 'hello'}]
        translated = [{'start': 0, 'end': 1, 'text': 'Hallo', 'text_orig': 'hello'}]
        for dub in [False, True]:
            with self.subTest(dub=dub), patch.object(dubbing.video_download, 'download', return_value=self.root / 'video.mp4') as download, \
                    patch.object(dubbing.stt_client, 'extract_audio', return_value=self.root / 'audio.wav') as extract, \
                    patch.object(dubbing.stt_client, 'transcribe', return_value=segments) as transcribe, \
                    patch.object(dubbing.stt_client, 'write_outputs', return_value={'srt': 'subtitles.srt'}) as outputs, \
                    patch.object(dubbing.translation, 'translate_srt', return_value=translated) as translate, \
                    patch.object(dubbing.tts_client, 'load_cfg', return_value={'backend': 'piper'}), \
                    patch.object(dubbing.tts_client, 'synth_lines', return_value=[self.root / 'dub.wav']) as synth, \
                    patch.object(dubbing, 'assemble') as assemble:
                dubbing.run('https://video.example.test', None, 'de', dub, 'en')
                download.assert_called_once_with('https://video.example.test', self.root / 'dub')
                extract.assert_called_once_with(self.root / 'video.mp4')
                transcribe.assert_called_once_with(self.root / 'audio.wav')
                translate.assert_called_once_with(segments, 'en', 'de')
                self.assertEqual([c.args[0] for c in outputs.call_args_list], [segments, translated])
                if dub:
                    synth.assert_called_once_with(translated, self.root / 'dub' / 'video.dub')
                    assemble.assert_called_once_with(self.root / 'video.mp4', [self.root / 'dub.wav'], translated, self.root / 'dub' / 'video.dubbed.de.mp4')
                else:
                    synth.assert_not_called()
                    assemble.assert_not_called()

    def test_generation_clis_forward_explicit_options(self):
        with patch.object(sys, 'argv', ['image_pipeline.py', '--prompt', 'tree', '--out', str(self.root / 'img.png'), '--width', '640', '--height', '480', '--no-enhance']), \
                patch.object(image_pipeline.image_gen, 'generate') as generate:
            image_pipeline.main()
        generate.assert_called_once_with('tree', self.root / 'img.png', enhance_prompt=False, width=640, height=480)
        with patch.object(sys, 'argv', ['video_pipeline.py', '--prompt', 'tree', '--out', str(self.root / 'vid.mp4'), '--workflow', 'minimax_video', '--model', 'custom', '--no-enhance']), \
                patch.object(video_pipeline.video_gen, 'generate') as generate:
            video_pipeline.main()
        generate.assert_called_once_with('tree', self.root / 'vid.mp4', workflow='minimax_video', model='custom', width=video_pipeline.C.IMAGE_WIDTH, height=video_pipeline.C.IMAGE_HEIGHT, enhance_prompt=False)

    def test_dubbing_cli_requires_input_before_starting(self):
        with patch.object(sys, 'argv', ['download_translate_dub.py']), patch.object(dubbing, 'run') as run, \
                patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as exited:
            dubbing.main()
        self.assertEqual(exited.exception.code, 2)
        run.assert_not_called()
