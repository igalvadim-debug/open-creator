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
