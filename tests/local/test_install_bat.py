"""Windows 安装入口的离线集成测试：解释器选择、参数转发和失败处理。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == 'win32', 'requires Windows cmd.exe')
class InstallBatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sandbox = Path(temp.name)
        self.root = self.sandbox / 'repo with spaces'
        self.root.mkdir()
        shutil.copyfile(REPO / 'install.bat', self.root / 'install.bat')
        # Replace the expensive installer and stack with local recording fixtures.
        (self.root / 'install.py').write_text(
            'import json, os, sys\n'
            'from pathlib import Path\n'
            'Path("invocation.json").write_text(json.dumps({\n'
            '    "argv": sys.argv[1:], "cwd": os.getcwd(),\n'
            '    "python": sys.executable,\n'
            '    "utf8": os.environ.get("PYTHONUTF8"),\n'
            '    "encoding": os.environ.get("PYTHONIOENCODING"),\n'
            '}), encoding="utf-8")\n'
            'sys.exit(int(os.environ.get("TEST_INSTALL_STATUS", "0")))\n',
            encoding='utf-8',
        )
        (self.root / 'start.bat').write_bytes(
            b'@echo off\r\necho started>stack-started.txt\r\nexit /b 0\r\n')
        self.system32 = Path(os.environ['SystemRoot']) / 'System32'
        self.cmd = self.system32 / 'cmd.exe'
        self.env = os.environ.copy()
        # Remove developer-machine Python/launcher discovery and startup hooks.
        for key in list(self.env):
            if key.upper().startswith('PYTHON') or key.upper().startswith('PYLAUNCHER'):
                del self.env[key]
        self.env.update({
            'PATH': str(self.system32),
            'LOCALAPPDATA': str(self.sandbox / 'local-app-data'),
            'TEST_INSTALL_STATUS': '0',
        })

    def create_python(self, directory):
        # No pip, packages, downloads, or external services are needed.
        venv.EnvBuilder(with_pip=False).create(directory)
        return directory / 'Scripts/python.exe'

    def run_batch(self, *args, answer='N'):
        # Starting outside the repo also verifies cd /d "%~dp0".
        command = subprocess.list2cmdline([str(self.root / 'install.bat'), *args])
        return subprocess.run(
            # cmd.exe parses quotes itself; a list would apply CRT escaping again.
            f'"{self.cmd}" /d /s /c "{command}"',
            cwd=self.sandbox, env=self.env, input=(answer + '\r\n').encode('ascii'),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10,
        )

    def invocation(self):
        return json.loads((self.root / 'invocation.json').read_text(encoding='utf-8'))

    def test_missing_installer_fails_without_starting_the_stack(self):
        (self.root / 'install.py').unlink()
        result = self.run_batch(answer='Y')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertFalse((self.root / 'invocation.json').exists())
        self.assertFalse((self.root / 'stack-started.txt').exists())

    def test_missing_python_fails_without_running_installer_or_stack(self):
        result = self.run_batch(answer='Y')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertFalse((self.root / 'invocation.json').exists())
        self.assertFalse((self.root / 'stack-started.txt').exists())

    def test_existing_venv_takes_priority_and_forwards_arguments_and_utf8_environment(self):
        python = self.create_python(self.root / 'venv')
        local_python = Path(self.env['LOCALAPPDATA']) / 'Programs/Python/Python312/python.exe'
        local_python.parent.mkdir(parents=True)
        local_python.write_bytes(b'invalid executable: must not be selected')
        args = ['--python', r'C:\Python Custom\python.exe', '--example']
        result = self.run_batch(*args)
        self.assertEqual(result.returncode, 0, result.stdout)
        invocation = self.invocation()
        self.assertEqual(Path(invocation['python']), python)
        self.assertEqual(Path(invocation['cwd']), self.root)
        self.assertEqual(invocation['argv'], args)
        self.assertEqual(invocation['utf8'], '1')
        self.assertEqual(invocation['encoding'], 'utf-8')
        self.assertFalse((self.root / 'stack-started.txt').exists())

    def test_python_on_path_is_used_when_venv_local_install_and_py_launcher_are_absent(self):
        python = self.create_python(self.sandbox / 'tools')
        self.env['PATH'] = os.pathsep.join([str(python.parent), str(self.system32)])
        result = self.run_batch()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(Path(self.invocation()['python']), python)
        self.assertFalse((self.root / 'stack-started.txt').exists())

    def test_installer_failure_returns_failure_without_launching_the_stack(self):
        self.create_python(self.root / 'venv')
        self.env['TEST_INSTALL_STATUS'] = '37'
        result = self.run_batch(answer='Y')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue((self.root / 'invocation.json').exists())
        self.assertFalse((self.root / 'stack-started.txt').exists())

    def test_accepting_launch_prompt_calls_start_bat_after_success(self):
        self.create_python(self.root / 'venv')
        result = self.run_batch(answer='Y')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((self.root / 'invocation.json').exists())
        self.assertEqual((self.root / 'stack-started.txt').read_text().strip(), 'started')

    @unittest.expectedFailure
    def test_local_python_installation_in_path_with_spaces(self):
        """已知回归：install.bat 的 %PYEXE% 未加引号，包含空格的路径无法启动。"""
        self.env['LOCALAPPDATA'] = str(self.sandbox / 'user profile' / 'AppData/Local')
        directory = Path(self.env['LOCALAPPDATA']) / 'Programs/Python/Python312'
        # Keep pyvenv.cfg immediately above the relocated Scripts directory.
        self.create_python(directory.parent)
        (directory.parent / 'Scripts').rename(directory)
        result = self.run_batch()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((self.root / 'invocation.json').exists())
