"""open-creator LOCAL — установка окружения (Windows).

Создаёт локальное venv (./venv) из указанного CPython, «активирует» его
(для установки и запуска используется интерпретатор напрямую — эквивалент
activate без лишней оболочки), ставит requirements.txt ЛОКАЛЬНО (без отправки
кода/данных куда-либо; качаются только пакеты PyPI и веса моделей), затем
скачивает модели (`local-stack/setup_models.py`, только свои GGUF-веса в
./local-stack/models/), ставит JS-зависимости веб-интерфейса
(corepack enable + pnpm install) и генерирует start.bat для запуска стека.

Веб-интерфейс (open-creator UI): http://127.0.0.1:19861/ — поднимается
командой `pnpm web:dev` после того, как local-stack запущен (start.bat).
Для локального режима daemon использует OPENCREATOR_LOCAL=1 (см. .env.example).

Использование:
    "C:\\Users\\Startklar\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" install.py
Либо просто запустить start.bat — при отсутствии venv он сам вызовет install.py.
Всё остаётся внутри этой папки репозитория: venv, модели, кэш pip/node — local.
"""
from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "venv"
REQUIREMENTS = ROOT / "requirements.txt"
MODELS_DIR = ROOT / "local-stack" / "models"

# Интерпретатор по умолчанию (можно переопределить аргументом --python).
DEFAULT_PYTHON = r"C:\Users\Startklar\AppData\Local\Programs\Python\Python312\python.exe"


def venv_python() -> Path:
    """Путь к python.exe внутри venv (Windows) или bin/python (POSIX)."""
    if os_name_is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def os_name_is_windows() -> bool:
    """Return whether the current Python platform is Windows."""
    return sys.platform.startswith("win")


def run(cmd: list[str]) -> int:
    """Run cmd from the repository root and return its exit status.

    Nonzero statuses are returned without raising; process launch errors
    propagate as OSError.
    """
    print("+ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def ensure_venv(base_python: str) -> Path:
    """Return the interpreter in ROOT/venv, creating it if needed.

    Use base_python for creation; reuse an existing interpreter path without
    checking base_python.
    Raise SystemExit if base_python is absent or creation leaves no
    interpreter. Creation failures propagate as subprocess.CalledProcessError;
    process launch errors propagate as OSError.
    """
    py = venv_python()
    if py.exists():
        print(f"[ok  ] venv уже существует: {VENV_DIR}")
        return py
    if not Path(base_python).exists():
        raise SystemExit(
            f"[fail] Python не найден: {base_python}\n"
            f"       Укажите свой: python install.py --python <путь к python.exe>"
        )
    print(f"[setup] Создаю venv: {VENV_DIR} (из {base_python})")
    subprocess.check_call(
        [base_python, "-m", "venv", str(VENV_DIR)], cwd=str(ROOT)
    )
    if not py.exists():
        raise SystemExit(f"[fail] Неожиданно: {py} не появился после создания venv")
    return py


def activate_and_install(py: Path) -> None:
    """Upgrade pip, setuptools, and wheel; install requirements.txt via py.

    The parent process environment is unchanged. A nonzero packaging-tool
    upgrade status is ignored. Raise SystemExit if requirements.txt is missing
    or its installation exits nonzero; process launch errors propagate as
    OSError.
    """
    env_prefix = VENV_DIR / ("Scripts" if os_name_is_windows() else "bin")
    print(f"[activ ] VIRTUAL_ENV={VENV_DIR} PATH~={env_prefix}")
    # Обновление pip/setuptools внутри venv (только PyPI, локально).
    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    if not REQUIREMENTS.exists():
        raise SystemExit(f"[fail] Нет файла требований: {REQUIREMENTS}")
    rc = run([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    if rc != 0:
        raise SystemExit("[fail] Не удалось установить requirements.txt")
    print("[ok    ] Зависимости установлены в venv (все локально, без внешних AI API)")


def download_models(py: Path) -> int:
    """Run the model setup script using interpreter py; return its exit status.

    The script downloads missing GGUF files to its configured model directory.
    It catches individual download errors, so success does not ensure all
    models are present. Return 1 when the script is missing (treated as a
    failed setup); otherwise return the script's exit status unchanged.
    Process launch errors propagate as OSError.
    """
    setup = ROOT / "local-stack" / "setup_models.py"
    if not setup.exists():
        print("[fail ] local-stack/setup_models.py не найден — модели не скачаны")
        return 1
    print("[models] Скачиваю модели локально в ./local-stack/models ...")
    rc = run([str(py), str(setup)])
    if rc != 0:
        print("[fail  ] Скачивание моделей завершилось с ошибкой;"
              " повторите позже: venv python local-stack/setup_models.py")
    else:
        print(f"[ok    ] Модели на месте: {MODELS_DIR}")
    return rc


def install_web_deps() -> int:
    """Install the web UI JS dependencies via corepack/pnpm; return exit status.

    Runs `corepack enable` then `pnpm install` from the repository root
    (packageManager in package.json pins pnpm). Nonzero statuses are returned
    without raising; process launch errors (e.g. Node.js/corepack missing)
    propagate as OSError.
    """
    print("[web   ] Ставлю JS-зависимости веб-интерфейса (corepack + pnpm) ...")
    rc = run(["corepack", "enable"])
    if rc != 0:
        print("[fail  ] corepack enable не удался — нужен Node.js 16.13+ "
              "(https://nodejs.org); веб-интерфейс можно поставить позже: pnpm install")
        return rc
    rc = run(["pnpm", "install"])
    if rc != 0:
        print("[fail  ] pnpm install завершился с ошибкой;"
              " повторите позже: pnpm install")
    else:
        print("[ok    ] Веб-интерфейс установлен: запуск `pnpm web:dev`,"
              " затем http://127.0.0.1:19861/")
    return rc


START_BAT = """@echo off
rem open-creator LOCAL — запуск стека (LLM :8484, embeddings :8512, MCP :8001 ...)
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title open-creator LOCAL

rem ---------------------------------------------------------------
rem  start.bat   -> локальный стек (local-stack), затем веб-интерфейс
rem  start.bat stop -> все сервисы стека остановить (Ctrl+C в этом окне)
rem  Веб-интерфейс после старта: http://127.0.0.1:19861/
rem ---------------------------------------------------------------

if /i "%~1"=="stop" goto :stop

if not exist "venv\\Scripts\\python.exe" (
    echo venv не найден — запускаю установку...
    "C:\\Users\\Startklar\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" install.py
    if errorlevel 1 (
        echo [fail] Установка не удалась.
        pause
        exit /b 1
    )
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set OPENCREATOR_LOCAL=1

echo [1/2] Запускаю local-stack (llama-server :8484, embeddings :8512, MCP :8001)...
start "open-creator-local-stack" cmd /k ""venv\\Scripts\\activate.bat" && python local-stack\\start.py"

echo [2/2] Запускаю веб-интерфейс (pnpm web:dev)...
timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:19861/
pnpm web:dev

echo Готово. Закройте окно стека или выполните: start.bat stop
pause
exit /b 0

:stop
echo Останавливаю весь стек — закройте окна «open-creator-local-stack» и dev-сервера
echo (или нажмите Ctrl+C в них).
taskkill /f /im llama-server.exe >nul 2>&1
powershell -NoProfile -Command "foreach($p in 8001,8002,8003,8484,8512,19861){ Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('Port ' + $p + ': PID ' + $_.OwningProcess + ' остановлен') } }"
exit /b 0

endlocal
"""


def write_start_bat() -> None:
    """Create or overwrite ROOT/start.bat with the UTF-8 Windows launcher.

    File write errors propagate as OSError.
    """
    bat = ROOT / "start.bat"
    bat.write_text(START_BAT.replace("\n", "\r\n"), encoding="utf-8")
    print(f"[ok    ] Создан {bat.name}: двойной клик или .\\start.bat")


def main(argv: list[str]) -> int:
    """Prepare the venv, install dependencies/models/web UI, write start.bat.

    argv excludes the program name. The value after the first --python wins;
    without --python, argv[0] is used only when at least two arguments are
    present and it does not start with '-'. Otherwise DEFAULT_PYTHON is used,
    including when --python has no following value.

    Return 0 only after all steps complete, including successful model setup;
    start.bat is written and "Готово" printed only on that success path. When
    model setup exits nonzero, do not write start.bat or print "Готово", and
    return its (nonzero) status as an installation failure. Web-UI dependency
    install failures (corepack/pnpm) are reported but nonfatal: the Python
    stack still works and `pnpm install` can be retried later. Setup
    SystemExit, subprocess.CalledProcessError, and OSError exceptions
    propagate.
    """
    base_python = DEFAULT_PYTHON
    if "--python" in argv:
        i = argv.index("--python")
        if i + 1 < len(argv):
            base_python = argv[i + 1]
    elif len(argv) >= 2 and not argv[0].startswith("-"):
        base_python = argv[0]

    print("=== open-creator LOCAL installer (всё в этой папке) ===")
    py = ensure_venv(base_python)
    activate_and_install(py)
    models_rc = download_models(py)
    if models_rc != 0:
        print("[fail] Установка не завершена: модели не установлены."
              " Повторите: venv python local-stack/setup_models.py")
        return models_rc
    web_rc = install_web_deps()
    if web_rc != 0:
        print("[warn] Веб-интерфейс не установлен (нужен Node.js + pnpm);"
              " Python-стек готов, повторите позже: corepack enable && pnpm install")
    write_start_bat()
    print("=== Готово. Запуск: start.bat (стек + веб-интерфейс :19861) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
