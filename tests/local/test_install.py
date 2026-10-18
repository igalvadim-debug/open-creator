"""安装失败恢复、解释器选择和模型下载退出状态的离线回归测试。"""
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_module('local_installer', REPO / 'install.py')
setup_models = load_module('installer_model_setup', REPO / 'local-stack/setup_models.py')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in {
            'ROOT': self.root,
            'VENV_DIR': self.root / 'venv',
            'REQUIREMENTS': self.root / 'requirements.txt',
            'INSTALL_COMPLETE': self.root / 'venv/.install-complete',
        }.items():
            patcher = patch.object(installer, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        patcher = patch('sys.stdout', self.output)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.py = installer.venv_python()
        self.py.parent.mkdir(parents=True)
        self.py.touch()
        installer.REQUIREMENTS.write_text('example-package\n', encoding='utf-8')
        self.setup = self.root / 'local-stack/setup_models.py'
        self.setup.parent.mkdir()
        self.setup.touch()

    def test_interpreter_selection_for_default_positional_and_option(self):
        for argv, expected in [
            ([], sys.executable),
            (['C:/Python Custom/python.exe'], 'C:/Python Custom/python.exe'),
            (['--python', 'D:/Python/python.exe'], 'D:/Python/python.exe'),
        ]:
            with self.subTest(argv=argv), \
                    patch.object(installer, 'ensure_venv', return_value=self.py) as ensure, \
                    patch.object(installer, 'run', return_value=0):
                self.assertEqual(installer.main(argv), 0)
                ensure.assert_called_once_with(expected)

    def test_venv_creation_uses_selected_interpreter(self):
        self.py.unlink()
        selected = self.root / 'Python Custom/python.exe'
        selected.parent.mkdir()
        selected.touch()
        with patch.object(installer.subprocess, 'check_call',
                          side_effect=lambda *args, **kwargs: self.py.touch()) as create:
            self.assertEqual(installer.ensure_venv(str(selected)), self.py)
        create.assert_called_once_with(
            [str(selected), '-m', 'venv', str(installer.VENV_DIR)], cwd=str(self.root))

    def test_success_marks_complete_only_after_dependencies_models_and_launcher(self):
        def run_step(cmd):
            self.assertFalse(installer.INSTALL_COMPLETE.exists())
            self.assertFalse((self.root / 'start.bat').exists())
            return 0

        with patch.object(installer, 'run', side_effect=run_step) as run, \
                patch.object(installer, 'install_web_deps', return_value=0):
            self.assertEqual(installer.main([]), 0)
        self.assertEqual(run.call_count, 3)
        self.assertTrue(installer.INSTALL_COMPLETE.is_file())
        launcher = (self.root / 'start.bat').read_bytes()
        self.assertEqual(launcher, installer.START_BAT.encode('utf-8'))
        self.assertIn('Готово', self.output.getvalue())

    def test_model_failure_returns_status_without_launcher_or_stale_marker(self):
        installer.INSTALL_COMPLETE.touch()
        with patch.object(installer, 'run', side_effect=[0, 0, 7]):
            self.assertEqual(installer.main([]), 7)
        self.assertFalse((self.root / 'start.bat').exists())
        self.assertFalse(installer.INSTALL_COMPLETE.exists())
        self.assertNotIn('Готово', self.output.getvalue())

    def test_requirements_failure_can_be_retried_with_existing_venv(self):
        installer.INSTALL_COMPLETE.touch()
        with patch.object(installer, 'run', side_effect=[0, 1]) as run:
            with self.assertRaises(SystemExit):
                installer.main([])
        self.assertEqual(run.call_count, 2)
        self.assertFalse(installer.INSTALL_COMPLETE.exists())
        self.assertFalse((self.root / 'start.bat').exists())
        with patch.object(installer, 'run', return_value=0), \
                patch.object(installer, 'install_web_deps', return_value=0):
            self.assertEqual(installer.main([]), 0)
        self.assertTrue(installer.INSTALL_COMPLETE.is_file())

    def test_missing_model_setup_is_an_installation_failure(self):
        self.setup.unlink()
        with patch.object(installer, 'run', return_value=0) as run:
            self.assertEqual(installer.main([]), 1)
        self.assertEqual(run.call_count, 2)
        self.assertFalse(installer.INSTALL_COMPLETE.exists())
        self.assertFalse((self.root / 'start.bat').exists())
        self.assertNotIn('Готово', self.output.getvalue())

    def test_launcher_write_failure_does_not_mark_installation_complete(self):
        with patch.object(installer, 'run', return_value=0), \
                patch.object(installer, 'write_start_bat', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                installer.main([])
        self.assertFalse(installer.INSTALL_COMPLETE.exists())
        self.assertNotIn('Готово', self.output.getvalue())


class LauncherWriteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / '项目 with spaces'
        self.root.mkdir()
        self.launcher = self.root / 'start.bat'
        self.marker = self.root / 'venv/.install-complete'
        for name, value in {'ROOT': self.root, 'INSTALL_COMPLETE': self.marker}.items():
            patcher = patch.object(installer, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('sys.stdout', new_callable=io.StringIO)
        self.output = patcher.start()
        self.addCleanup(patcher.stop)

    def test_new_launcher_uses_exact_utf8_lf_bytes_and_creates_marker_directory(self):
        self.assertFalse(self.marker.parent.exists())
        installer.write_start_bat()
        data = self.launcher.read_bytes()
        self.assertEqual(data, installer.START_BAT.encode('utf-8'))
        self.assertNotIn(b'\r', data)
        self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
        self.assertTrue(self.marker.is_file())
        self.assertEqual(self.marker.read_bytes(), b'')

    def test_outdated_launchers_are_replaced_with_exact_current_bytes(self):
        expected = installer.START_BAT.encode('utf-8')
        for old in (b'', b'@echo off\nrem obsolete launcher\n',
                    expected.replace(b'\n', b'\r\n'), b'\xef\xbb\xbf' + expected):
            with self.subTest(old=old[:40]):
                self.marker.unlink(missing_ok=True)
                self.launcher.write_bytes(old)
                installer.write_start_bat()
                self.assertEqual(self.launcher.read_bytes(), expected)
                self.assertTrue(self.marker.is_file())

    def test_identical_launcher_is_not_rewritten_but_missing_marker_is_restored(self):
        self.launcher.write_bytes(installer.START_BAT.encode('utf-8'))
        before = self.launcher.stat().st_mtime_ns
        with patch.object(Path, 'write_bytes', side_effect=AssertionError('unnecessary rewrite')):
            installer.write_start_bat()
            installer.write_start_bat()
        self.assertEqual(self.launcher.stat().st_mtime_ns, before)
        self.assertTrue(self.marker.is_file())

    def test_completion_marker_is_created_only_after_complete_launcher_write(self):
        write_bytes = Path.write_bytes

        def write(path, data):
            self.assertEqual(path, self.launcher)
            self.assertFalse(self.marker.exists())
            return write_bytes(path, data)

        with patch.object(Path, 'write_bytes', autospec=True, side_effect=write) as written:
            installer.write_start_bat()
        written.assert_called_once_with(self.launcher, installer.START_BAT.encode('utf-8'))
        self.assertTrue(self.marker.is_file())

    def test_launcher_write_errors_propagate_without_creating_marker_or_success_message(self):
        for old in (None, b'obsolete launcher'):
            with self.subTest(old=old):
                if old is not None:
                    self.launcher.write_bytes(old)
                error = PermissionError('launcher is not writable')
                with patch.object(Path, 'write_bytes', side_effect=error), \
                        self.assertRaises(PermissionError) as raised:
                    installer.write_start_bat()
                self.assertIs(raised.exception, error)
                self.assertFalse(self.marker.exists())
                self.assertNotIn('[ok', self.output.getvalue())
                if old is None:
                    self.assertFalse(self.launcher.exists())
                else:
                    self.assertEqual(self.launcher.read_bytes(), old)

    def test_existing_launcher_read_error_does_not_overwrite_it_or_mark_complete(self):
        self.launcher.write_bytes(b'existing launcher')
        error = PermissionError('launcher is not readable')
        with patch.object(Path, 'read_bytes', side_effect=error), \
                patch.object(Path, 'write_bytes') as write, \
                self.assertRaises(PermissionError) as raised:
            installer.write_start_bat()
        self.assertIs(raised.exception, error)
        write.assert_not_called()
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.launcher.read_bytes(), b'existing launcher')
        self.assertNotIn('[ok', self.output.getvalue())

    def test_marker_directory_failure_propagates_after_launcher_write(self):
        self.marker.parent.write_bytes(b'a file blocks the venv directory')
        with self.assertRaises(OSError):
            installer.write_start_bat()
        self.assertEqual(self.launcher.read_bytes(), installer.START_BAT.encode('utf-8'))
        self.assertFalse(self.marker.exists())
        self.assertNotIn('[ok', self.output.getvalue())

    def test_marker_touch_failure_propagates_and_can_be_retried_without_rewriting(self):
        error = PermissionError('completion marker is not writable')
        with patch.object(Path, 'touch', side_effect=error), \
                self.assertRaises(PermissionError) as raised:
            installer.write_start_bat()
        self.assertIs(raised.exception, error)
        self.assertEqual(self.launcher.read_bytes(), installer.START_BAT.encode('utf-8'))
        self.assertFalse(self.marker.exists())
        self.assertNotIn('[ok', self.output.getvalue())
        with patch.object(Path, 'write_bytes', side_effect=AssertionError('unnecessary rewrite')):
            installer.write_start_bat()
        self.assertTrue(self.marker.is_file())

    def test_main_removes_stale_marker_before_real_launcher_write_fails(self):
        self.marker.parent.mkdir()
        self.marker.touch()
        self.launcher.write_bytes(b'obsolete launcher')
        with patch.object(installer, 'ensure_venv', return_value=self.root / 'venv/python'), \
                patch.object(installer, 'activate_and_install'), \
                patch.object(installer, 'download_models', return_value=0), \
                patch.object(installer, 'install_web_deps', return_value=0), \
                patch.object(Path, 'write_bytes', side_effect=OSError('disk full')), \
                self.assertRaisesRegex(OSError, 'disk full'):
            installer.main([])
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.launcher.read_bytes(), b'obsolete launcher')
        self.assertNotIn('Готово', self.output.getvalue())


class ModelSetupTests(unittest.TestCase):
    def test_download_failure_sets_failure_status_and_continues_other_models(self):
        downloads = [('test/repo', 'first.gguf'), ('test/repo', 'second.gguf')]
        with patch.object(sys, 'argv', ['setup_models.py']), \
                patch.object(setup_models.C, 'ensure_dirs'), \
                patch.object(setup_models, 'DOWNLOADS', downloads), \
                patch.object(setup_models, 'download', side_effect=[OSError('offline'), Path('second.gguf')]) as download, \
                patch.object(setup_models, 'status'), \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(setup_models.main(), 1)
        self.assertEqual(download.call_count, 2)

    def test_successful_downloads_return_zero(self):
        with patch.object(sys, 'argv', ['setup_models.py']), \
                patch.object(setup_models.C, 'ensure_dirs'), \
                patch.object(setup_models, 'download'), \
                patch.object(setup_models, 'status'):
            self.assertEqual(setup_models.main(), 0)

    def test_list_only_does_not_download_or_fail_for_missing_models(self):
        with patch.object(sys, 'argv', ['setup_models.py', '--list']), \
                patch.object(setup_models.C, 'ensure_dirs'), \
                patch.object(setup_models, 'download') as download, \
                patch.object(setup_models, 'status') as status:
            self.assertEqual(setup_models.main(), 0)
        download.assert_not_called()
        status.assert_called_once_with()
