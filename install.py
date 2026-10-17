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
INSTALL_COMPLETE = VENV_DIR / ".install-complete"

# Интерпретатор по умолчанию (можно переопределить аргументом --python).
DEFAULT_PYTHON = sys.executable


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


def required_model_files() -> list[Path]:
    """Return target paths of the required model downloads declared in setup_models.py.

    Parses the DOWNLOADS list literal via ast; falls back to an empty list if
    the script or list is absent/unparsable (then no extra verification runs).
    """
    import ast
    setup = ROOT / "local-stack" / "setup_models.py"
    try:
        tree = ast.parse(setup.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "DOWNLOADS" for t in node.targets)):
            try:
                pairs = ast.literal_eval(node.value)
                return [MODELS_DIR / tail.rsplit("/", 1)[-1] for _repo, tail in pairs]
            except (ValueError, TypeError):
                return []
    return []


def download_models(py: Path) -> int:
    """Run the model setup script using interpreter py; return failure status.

    The script downloads missing GGUF files to its configured model directory.
    It catches individual download errors and always exits 0, so a nonzero
    result here reflects ANY failed/missing required download: return 1 when
    the script is missing, when the script exits nonzero, or when any required
    model file is still absent afterwards. Process launch errors propagate as
    OSError.
    """
    setup = ROOT / "local-stack" / "setup_models.py"
    if not setup.exists():
        print("[fail ] local-stack/setup_models.py не найден — модели не скачаны")
        return 1
    print("[models] Скачиваю модели локально в ./local-stack/models ...")
    rc = run([str(py), str(setup)])
    missing = [p.name for p in required_model_files() if not p.exists()]
    if rc != 0 or missing:
        if missing:
            print(f"[fail  ] Не хватает моделей: {', '.join(missing)}")
        print("[fail  ] Скачивание моделей завершилось с ошибкой;"
              " повторите позже: venv python local-stack/setup_models.py")
        return rc if rc != 0 else 1
    print(f"[ok    ] Модели на месте: {MODELS_DIR}")
    return 0


def install_web_deps() -> int:
    """Install the web UI JS dependencies via corepack/pnpm; return exit status.

    Runs `corepack enable` then `pnpm install` from the repository root
    (packageManager in package.json pins pnpm). Nonzero statuses are returned
    without raising; process launch errors (e.g. missing Corepack executable)
    are converted to a nonzero status (1) instead of propagating, so callers
    can keep their warning flow and still write start.bat.
    """
    print("[web   ] Ставлю JS-зависимости веб-интерфейса (corepack + pnpm) ...")
    try:
        rc = run(["corepack", "enable"])
    except OSError as e:
        print(f"[fail  ] corepack не запущен ({e}) — нужен Node.js 16.13+ "
              "(https://nodejs.org); веб-интерфейс можно поставить позже: pnpm install")
        return 1
    if rc != 0:
        print("[fail  ] corepack enable не удался — нужен Node.js 16.13+ "
              "(https://nodejs.org); веб-интерфейс можно поставить позже: pnpm install")
        return rc
    try:
        rc = run(["pnpm", "install"])
    except OSError as e:
        print(f"[fail  ] pnpm не запущен ({e}); повторите позже: pnpm install")
        return 1
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

if not exist "venv\\Scripts\\python.exe" goto install
if not exist "venv\\.install-complete" goto install
goto start

:install
echo Установка не завершена — запускаю установку...
if exist "venv\\Scripts\\python.exe" (
    "venv\\Scripts\\python.exe" install.py
) else (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [fail] Установка не удалась.
        pause
        exit /b 1
    )
)
if errorlevel 1 (
    echo [fail] Установка не удалась.
    exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set OPENCREATOR_LOCAL=1

echo [1/2] Запускаю local-stack (llama-server :8484, embeddings :8512, MCP :8001)...
rem Стек сам пишет PID-файл local-stack\\.pids — "start.bat stop" остановит только его
start "open-creator-local-stack" cmd /k ""venv\\Scripts\\activate.bat" && python local-stack\\start.py"

echo [2/2] Запускаю веб-интерфейс (pnpm web:dev)...
timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:19861/
rem PID-обёртка пишет .webui.pid и останавливает при Ctrl+C только своё дерево
node scripts\\web-dev-wrapper.mjs pnpm web:dev

echo Готово. Закройте окно стека или выполните: start.bat stop
pause
exit /b 0

:stop
echo Останавливаю только процессы, записанные этим лаунчером (.pids / .webui.pid) ...
rem Стек: local-stack/start.py --stop шлёт сигнал только PID из local-stack\\.pids
if exist "venv\\Scripts\\python.exe" ("venv\\Scripts\\python.exe" local-stack\\start.py --stop) else (python local-stack\\start.py --stop)
rem Веб-интерфейс: обёртка сверяет имя процесса перед остановкой; чужие не трогает
if exist ".webui.pid" (
    node scripts\\web-dev-wrapper.mjs --stop ".webui.pid" || echo [warn] веб-интерфейс: процесс не найден или уже завершён
    del /q ".webui.pid" 2>nul
) else (
    echo [skip] .webui.pid нет — веб-интерфейс не запускался этим лаунчером
)
echo Готово. Чужие llama-server и слушатели портов не тронуты.
exit /b 0

endlocal
"""


def write_start_bat() -> None:
    """Create or overwrite ROOT/start.bat with the UTF-8 Windows launcher.

    File write errors propagate as OSError.
    """
    bat = ROOT / "start.bat"
    bat.write_text(START_BAT, encoding="utf-8")
    print(f"[ok    ] Создан {bat.name}: двойной клик или .\\start.bat")


def main(argv: list[str]) -> int:
    """Prepare the venv, install dependencies/models/web UI, write start.bat.

    argv excludes the program name. The value after the first --python wins;
    without --python, argv[0] is used when present and it does not start
    with '-'. Otherwise DEFAULT_PYTHON is used,
    including when --python has no following value.

    Return the nonzero model setup status (1 if its script is missing),
    skipping web dependency installation and launcher creation. Otherwise,
    attempt web dependency installation, create or overwrite start.bat, and
    return 0 even if corepack/pnpm returns a nonzero status. Individual model
    download errors are caught by the setup script, so a zero status does not
    guarantee that all models are present. Setup SystemExit,
    subprocess.CalledProcessError, and OSError exceptions propagate, including
    web process launch errors and launcher write errors.
    """
    base_python = DEFAULT_PYTHON
    if "--python" in argv:
        i = argv.index("--python")
        if i + 1 < len(argv):
            base_python = argv[i + 1]
    elif argv and not argv[0].startswith("-"):
        base_python = argv[0]

    print("=== open-creator LOCAL installer (всё в этой папке) ===")
    py = ensure_venv(base_python)
    INSTALL_COMPLETE.unlink(missing_ok=True)
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
