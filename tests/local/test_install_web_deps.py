"""网页依赖安装的离线单元测试：命令解析、失败处理及启动器回归。"""
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('web_deps_installer', REPO / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class WebDependencyTests(unittest.TestCase):
    COREPACK = r'C:\Program Files\nodejs\corepack.cmd'
    PNPM = r'C:\Program Files\nodejs\pnpm.cmd'

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'repo with spaces'
        self.root.mkdir()
        for name, value in {
            'ROOT': self.root,
            'INSTALL_COMPLETE': self.root / 'venv/.install-complete',
        }.items():
            patcher = patch.object(installer, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        patcher = patch('sys.stdout', new_callable=io.StringIO)
        self.output = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(installer.shutil, 'which')
        self.which = patcher.start()
        self.addCleanup(patcher.stop)
        # Keep the real run() boundary, but never launch a package manager.
        patcher = patch.object(installer.subprocess, 'call')
        self.launch = patcher.start()
        self.addCleanup(patcher.stop)
        self.configure_tools()

    def configure_tools(self, corepack=COREPACK, pnpm=PNPM, results=(0, 0)):
        self.which.reset_mock()
        self.which.side_effect = lambda name: {'corepack': corepack, 'pnpm': pnpm}[name]
        self.launch.reset_mock()
        self.launch.side_effect = results
        self.output.seek(0)
        self.output.truncate()

    def assert_commands(self, *commands):
        self.assertEqual(self.launch.call_args_list, [
            call(command, cwd=str(self.root)) for command in commands
        ])

    def test_resolved_executables_preserve_paths_and_run_from_repository_root(self):
        paths = [
            (self.COREPACK, self.PNPM),
            ('/opt/node tools/bin/corepack', '/opt/pnpm tools/bin/pnpm'),
        ]
        for corepack, pnpm in paths:
            with self.subTest(corepack=corepack, pnpm=pnpm):
                self.configure_tools(corepack, pnpm)
                self.assertEqual(installer.install_web_deps(), 0)
                self.assert_commands([corepack, 'enable'], [pnpm, 'install'])
                self.assertEqual(self.which.call_args_list, [call('corepack'), call('pnpm')])
                self.assertIn('[ok    ]', self.output.getvalue())
                self.assertIn('pnpm web:dev', self.output.getvalue())

    def test_missing_corepack_reports_recovery_without_launching_any_process(self):
        self.configure_tools(corepack=None)
        self.assertEqual(installer.install_web_deps(), 1)
        self.which.assert_called_once_with('corepack')
        self.launch.assert_not_called()
        output = self.output.getvalue()
        self.assertIn('[fail  ]', output)
        self.assertIn('corepack', output)
        self.assertIn('Node.js 16.13+', output)
        self.assertIn('pnpm install', output)
        self.assertNotIn('[ok    ]', output)

    def test_corepack_nonzero_status_is_preserved_and_stops_pnpm_installation(self):
        for status in (1, 27, -15):
            with self.subTest(status=status):
                self.configure_tools(results=(status,))
                self.assertEqual(installer.install_web_deps(), status)
                self.assert_commands([self.COREPACK, 'enable'])
                self.which.assert_called_once_with('corepack')
                self.assertIn('[fail  ] corepack enable', self.output.getvalue())
                self.assertNotIn('[ok    ]', self.output.getvalue())

    def test_corepack_launch_errors_return_failure_and_stop_before_pnpm_lookup(self):
        for error_type in (FileNotFoundError, PermissionError, OSError):
            with self.subTest(error_type=error_type):
                error = error_type('cannot launch corepack')
                self.configure_tools(results=(error,))
                self.assertEqual(installer.install_web_deps(), 1)
                self.assert_commands([self.COREPACK, 'enable'])
                self.which.assert_called_once_with('corepack')
                self.assertIn(str(error), self.output.getvalue())
                self.assertIn('pnpm install', self.output.getvalue())
                self.assertNotIn('[ok    ]', self.output.getvalue())

    def test_pnpm_is_resolved_after_corepack_has_enabled_its_shim(self):
        def resolve(name):
            if name == 'corepack':
                self.launch.assert_not_called()
                return self.COREPACK
            self.assertEqual(name, 'pnpm')
            self.assert_commands([self.COREPACK, 'enable'])
            return self.PNPM

        def launch(command, **kwargs):
            if command == [self.COREPACK, 'enable']:
                self.which.assert_called_once_with('corepack')
            return 0

        self.which.side_effect = resolve
        self.launch.side_effect = launch
        self.assertEqual(installer.install_web_deps(), 0)
        self.assert_commands([self.COREPACK, 'enable'], [self.PNPM, 'install'])

    def test_unresolved_pnpm_falls_back_to_bare_command(self):
        self.configure_tools(pnpm=None)
        self.assertEqual(installer.install_web_deps(), 0)
        self.assert_commands([self.COREPACK, 'enable'], ['pnpm', 'install'])
        self.assertEqual(self.which.call_args_list, [call('corepack'), call('pnpm')])
        self.assertIn('[ok    ]', self.output.getvalue())

    def test_pnpm_nonzero_status_is_preserved_for_resolved_and_fallback_commands(self):
        for pnpm in (self.PNPM, None):
            for status in (1, 42, -15):
                with self.subTest(pnpm=pnpm, status=status):
                    self.configure_tools(pnpm=pnpm, results=(0, status))
                    self.assertEqual(installer.install_web_deps(), status)
                    self.assert_commands([self.COREPACK, 'enable'], [pnpm or 'pnpm', 'install'])
                    self.assertIn('[fail  ] pnpm install', self.output.getvalue())
                    self.assertNotIn('[ok    ]', self.output.getvalue())

    def test_pnpm_launch_errors_return_failure_for_resolved_and_fallback_commands(self):
        for pnpm in (self.PNPM, None):
            for error_type in (FileNotFoundError, PermissionError, OSError):
                with self.subTest(pnpm=pnpm, error_type=error_type):
                    error = error_type('cannot launch pnpm')
                    self.configure_tools(pnpm=pnpm, results=(0, error))
                    self.assertEqual(installer.install_web_deps(), 1)
                    self.assert_commands([self.COREPACK, 'enable'], [pnpm or 'pnpm', 'install'])
                    self.assertIn(str(error), self.output.getvalue())
                    self.assertIn('pnpm install', self.output.getvalue())
                    self.assertNotIn('[ok    ]', self.output.getvalue())

    def test_web_dependency_failures_still_warn_and_create_launcher(self):
        failures = [
            (None, self.PNPM, ()),
            (self.COREPACK, self.PNPM, (7,)),
            (self.COREPACK, self.PNPM, (PermissionError('corepack denied'),)),
            (self.COREPACK, None, (0, FileNotFoundError('pnpm missing'))),
            (self.COREPACK, self.PNPM, (0, 9)),
        ]
        for corepack, pnpm, results in failures:
            with self.subTest(corepack=corepack, pnpm=pnpm, results=results):
                self.configure_tools(corepack, pnpm, results)
                launcher = self.root / 'start.bat'
                launcher.unlink(missing_ok=True)
                py = self.root / 'venv/bin/python'
                with patch.object(installer, 'ensure_venv', return_value=py), \
                        patch.object(installer, 'activate_and_install') as install_python, \
                        patch.object(installer, 'download_models', return_value=0) as download:
                    self.assertEqual(installer.main([]), 0)
                install_python.assert_called_once_with(py)
                download.assert_called_once_with(py)
                self.assertEqual(launcher.read_text(encoding='utf-8'), installer.START_BAT)
                self.assertIn('[warn]', self.output.getvalue())
                self.assertIn('corepack enable && pnpm install', self.output.getvalue())
