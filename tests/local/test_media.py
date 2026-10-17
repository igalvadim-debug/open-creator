"""Subtitle, local speech and video download behavior with synthetic files."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core import stt_client, tts_client, video_download


class MediaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for target in ['urllib.request.urlopen', 'subprocess.run']:
            patcher = patch(target, side_effect=AssertionError('unexpected external operation'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_srt_has_numbered_cues_and_millisecond_precision(self):
        self.assertEqual(stt_client.to_srt([{'start': 3661.125, 'end': 3663.5, 'text': 'Привет'}]),
                         '1\n01:01:01,125 --> 01:01:03,500\nПривет\n')
        self.assertEqual(stt_client.to_srt([]), '')

    def test_vtt_uses_dot_separated_milliseconds(self):
        self.assertEqual(stt_client.to_vtt([{'start': 1.125, 'end': 2.5, 'text': 'Hello'}]),
                         'WEBVTT\n\n00:00:01.125 --> 00:00:02.500\nHello\n')

    def test_write_outputs_creates_parent_and_unicode_text_files(self):
        segments = [{'start': 0, 'end': 1, 'text': 'Привет'}, {'start': 1, 'end': 2, 'text': '世界'}]
        result = stt_client.write_outputs(segments, self.root / 'nested' / 'captions.orig')
        self.assertEqual(set(result), {'srt', 'vtt', 'txt'})
        self.assertEqual(Path(result['txt']).read_text(encoding='utf-8'), 'Привет\n世界')
        self.assertEqual(Path(result['srt']).read_text(encoding='utf-8'), stt_client.to_srt(segments))
        self.assertTrue(Path(result['vtt']).read_text(encoding='utf-8').startswith('WEBVTT\n'))

    def test_whisper_model_is_loaded_lazily_and_reused(self):
        model_factory = MagicMock()
        with patch.object(stt_client, '_model', None), \
                patch.object(stt_client.C, 'WHISPER_MODELS_DIR', self.root / 'weights'), \
                patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=model_factory)}):
            self.assertIs(stt_client._get_whisper(), model_factory.return_value)
            self.assertIs(stt_client._get_whisper(), model_factory.return_value)
        model_factory.assert_called_once_with(stt_client.C.WHISPER_MODEL, device='auto', compute_type='auto', download_root=str(self.root / 'weights'))

    def test_faster_whisper_segments_are_materialized_and_trimmed(self):
        model = MagicMock()
        model.transcribe.return_value = (iter([SimpleNamespace(start=1.2, end=2.3, text=' hello ')]), object())
        with patch.object(stt_client.C, 'BIN_DIR', self.root), patch.object(stt_client, '_get_whisper', return_value=model):
            self.assertEqual(stt_client.transcribe(self.root / 'audio.wav'), [{'start': 1.2, 'end': 2.3, 'text': 'hello'}])
        model.transcribe.assert_called_once_with(str(self.root / 'audio.wav'), vad_filter=True)

    def test_whisper_cli_takes_priority_over_python_model(self):
        audio = self.root / 'audio.wav'
        (self.root / 'whisper-cli').touch()
        (self.root / f'ggml-{stt_client.C.WHISPER_MODEL}.bin').touch()
        audio.with_suffix('.whisper.txt').write_text('[1.0 --> 2.0]\n hello\n world\n', encoding='utf-8')
        with patch.object(stt_client.C, 'BIN_DIR', self.root), \
                patch.object(stt_client.C, 'WHISPER_MODELS_DIR', self.root), \
                patch.object(stt_client, '_get_whisper') as model, patch('subprocess.run') as run:
            self.assertEqual(stt_client.transcribe(audio), [{'start': 1.0, 'end': 2.0, 'text': 'hello world'}])
        model.assert_not_called()
        self.assertIn('-otxt', run.call_args.args[0])
        self.assertTrue(run.call_args.kwargs['check'])

    def test_audio_extraction_uses_mono_16khz_and_reuses_existing_output(self):
        video = self.root / 'clip.mp4'
        with patch('shutil.which', return_value='/usr/bin/ffmpeg'), patch('subprocess.run') as run:
            result = stt_client.extract_audio(video)
            self.assertEqual(result, self.root / 'clip.16k.wav')
            run.assert_called_once_with(['/usr/bin/ffmpeg', '-y', '-i', str(video), '-ar', '16000', '-ac', '1', str(result)], check=True, capture_output=True)
            result.touch()
            stt_client.extract_audio(video)
            self.assertEqual(run.call_count, 1)

    def test_tts_config_merges_json_and_prefers_matching_local_onnx_voice(self):
        cfg_file = self.root / 'config.json'
        cfg_file.write_text(json.dumps({'tts': {'backend': 'f5tts', 'language': 'de', 'speed': 1.5}}), encoding='utf-8')
        voices = self.root / 'comfy' / 'tts'
        voices.mkdir(parents=True)
        (voices / 'en_voice.onnx').touch()
        (voices / 'de_voice.onnx').touch()
        with patch.object(tts_client, 'CFG_FILE', cfg_file), patch.object(tts_client.C, 'CW_COMFY_LOCAL', voices.parent):
            cfg = tts_client.load_cfg()
        self.assertEqual(cfg['backend'], 'piper')
        self.assertEqual(cfg['voice'], 'de_voice')
        self.assertEqual(cfg['model_path'], str(voices))
        self.assertEqual(cfg['speed'], 1.5)

    def test_tts_config_uses_environment_defaults_when_file_and_catalog_are_absent(self):
        with patch.object(tts_client, 'CFG_FILE', self.root / 'missing.json'), \
                patch.object(tts_client.C, 'CW_COMFY_LOCAL', self.root / 'missing'):
            cfg = tts_client.load_cfg()
        self.assertEqual(cfg['voice'], tts_client.C.TTS_VOICE)
        self.assertEqual(cfg['backend'], tts_client.C.TTS_BACKEND)

    def test_piper_flat_and_nested_models_and_speed(self):
        for nested in [False, True]:
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as dirname:
                voices = Path(dirname)
                model = voices / 'voice.onnx' if not nested else voices / 'voice' / 'voice.onnx'
                model.parent.mkdir(exist_ok=True)
                model.touch()
                cfg = {'backend': 'Piper', 'model_path': str(voices), 'voice': 'voice', 'speed': 2}
                out = self.root / 'audio' / 'speech.wav'
                with patch.object(tts_client, 'load_cfg', return_value=cfg), \
                        patch('shutil.which', return_value='/usr/bin/piper'), \
                        patch('subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
                    self.assertEqual(tts_client.synth('Привет', out), out)
                run.assert_called_once_with(['/usr/bin/piper', '-m', str(model), '-f', str(out), '--length_scale', '0.5'], input='Привет'.encode(), capture_output=True)

    def test_piper_missing_model_and_failed_process_report_errors(self):
        cfg = {'backend': 'piper', 'model_path': str(self.root), 'voice': 'missing'}
        with patch.object(tts_client, 'load_cfg', return_value=cfg), self.assertRaisesRegex(RuntimeError, 'Piper'):
            tts_client.synth('hello', self.root / 'out.wav')
        (self.root / 'missing.onnx').touch()
        with patch.object(tts_client, 'load_cfg', return_value=cfg), \
                patch('shutil.which', return_value='piper'), \
                patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stderr=b'bad voice')), \
                self.assertRaisesRegex(RuntimeError, 'bad voice'):
            tts_client.synth('hello', self.root / 'out.wav')

    def test_openai_compatible_tts_writes_audio_and_rejects_external_base(self):
        cfg = {'backend': 'openai_compat', 'base_url': 'http://localhost:9000/v1/', 'voice': 'voice', 'speed': 1.1, 'model': 'local'}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'RIFF synthetic audio'
        out = self.root / 'out.wav'
        with patch.object(tts_client, 'load_cfg', return_value=cfg), patch('urllib.request.urlopen', return_value=response) as opened:
            self.assertEqual(tts_client.synth('hello', out), out)
        self.assertEqual(out.read_bytes(), b'RIFF synthetic audio')
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'http://localhost:9000/v1/audio/speech')
        self.assertEqual(json.loads(request.data), {'model': 'local', 'input': 'hello', 'voice': 'voice', 'speed': 1.1})
        cfg['base_url'] = 'https://external.example.test/v1'
        with patch.object(tts_client, 'load_cfg', return_value=cfg), self.assertRaisesRegex(RuntimeError, 'POLICY'):
            tts_client.synth('hello', out)

    def test_f5tts_and_unknown_backend(self):
        cfg = {'backend': 'f5tts', 'language': 'de', 'speaker': 'speaker'}
        with patch.object(tts_client, 'load_cfg', return_value=cfg), patch('subprocess.run') as run:
            tts_client.synth('hello', self.root / 'out.wav')
        self.assertEqual(run.call_args.args[0][-4:], ['--lang', 'de', '--speaker', 'speaker'])
        self.assertTrue(run.call_args.kwargs['check'])
        with patch.object(tts_client, 'load_cfg', return_value={'backend': 'unknown'}), self.assertRaisesRegex(RuntimeError, 'unknown'):
            tts_client.synth('hello', self.root / 'out.wav')

    def test_synth_lines_uses_stable_names_and_handles_empty_input(self):
        with patch.object(tts_client, 'synth', side_effect=lambda text, out: out) as synth:
            result = tts_client.synth_lines([{'text': 'one'}, {'text': 'two'}], self.root / 'dub.wav')
            self.assertEqual(result, [self.root / 'dub_00000.wav', self.root / 'dub_00001.wav'])
            self.assertEqual([call.args[0] for call in synth.call_args_list], ['one', 'two'])
            synth.reset_mock()
            self.assertEqual(tts_client.synth_lines([], self.root / 'dub.wav'), [])
            synth.assert_not_called()

    def test_download_returns_newest_mp4_and_passes_url_as_an_argument(self):
        old, new = self.root / 'old.mp4', self.root / 'new.mp4'
        old.touch()
        new.touch()
        os.utime(old, (1, 1))
        os.utime(new, (2, 2))
        url = 'https://video.example.test/watch?v=1&x=2'
        with patch('shutil.which', return_value='/usr/bin/yt-dlp'), patch('subprocess.run') as run:
            self.assertEqual(video_download.download(url, self.root), new)
        self.assertEqual(run.call_args.args[0], ['/usr/bin/yt-dlp', '-f', 'bv*+ba/b', '--merge-output-format', 'mp4', '-o', str(self.root / '%(title)s.%(ext)s'), url])
        self.assertEqual(run.call_args.kwargs, {'check': True})

    def test_download_missing_output_and_process_failure(self):
        with patch('shutil.which', return_value='yt-dlp'), patch('subprocess.run'), self.assertRaisesRegex(RuntimeError, 'yt-dlp'):
            video_download.download('https://video.example.test', self.root)
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'yt-dlp')), self.assertRaises(subprocess.CalledProcessError):
            video_download.download('https://video.example.test', self.root)

    def test_video_title_is_trimmed_with_an_empty_output_fallback(self):
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='  Title\n')):
            self.assertEqual(video_download.get_title('https://video.example.test'), 'Title')
        with patch('subprocess.run', return_value=SimpleNamespace(stdout='\n')):
            self.assertEqual(video_download.get_title('https://video.example.test'), 'video')
