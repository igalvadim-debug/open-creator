#!/usr/bin/env node
/**
 * web-dev-wrapper.mjs — PID-обёртка для `pnpm web:dev` (используется start.bat).
 *
 *   node scripts/web-dev-wrapper.mjs pnpm web:dev
 *     Запускает команду, пишет её PID и имя процесса в .webui.pid, ждёт
 *     завершения. При Ctrl+C/SIGTERM останавливает ТОЛЬКО своё дерево.
 *
 *   node scripts/web-dev-wrapper.mjs --stop [.webui.pid]
 *     Читает PID из файла, ПЕРЕД остановкой сверяет текущее имя процесса с
 *     записанным (формат: "<pid>\n<process name>"). Совпало — снимает дерево
 *     (Windows: taskkill /T /PID <pid>; POSIX: SIGTERM по потомкам из /proc).
 *     Процесс не найден или PID занят чужим процессом — код 1, ничего не убиваем.
 *
 * Никаких taskkill по имени образа и никакого kill по номеру порта — только
 * явно записанные этим лаунчером процессы.
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const IS_WIN = process.platform === "win32";
const PID_FILE_DEFAULT = ".webui.pid";

function readPidFile(file) {
  const raw = fs.readFileSync(file, "utf8").trim();
  const [pidStr, name] = raw.split(/\r?\n/);
  const pid = Number.parseInt(pidStr ?? "", 10);
  return { pid: Number.isInteger(pid) && pid > 0 ? pid : null, name: (name ?? "").trim() };
}

function procName(pid) {
  try {
    if (IS_WIN) {
      const r = spawnSync(
        "powershell",
        ["-NoProfile", "-Command", `(Get-CimInstance Win32_Process -Filter "ProcessId=${pid}").Name`],
        { encoding: "utf8", timeout: 5000 },
      );
      return (r.stdout ?? "").trim();
    }
    return fs.readFileSync(`/proc/${pid}/comm`, "utf8").trim();
  } catch {
    return "";
  }
}

function childPidsPosix(pid) {
  let direct = [];
  try {
    direct = fs
      .readFileSync(`/proc/${pid}/task/${pid}/children`, "utf8")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .map(Number);
  } catch {
    /* процесс уже завершился или нет прав на children */
  }
  const all = [];
  for (const c of direct) all.push(c, ...childPidsPosix(c));
  return all.filter(Boolean);
}

function killTree(pid) {
  if (IS_WIN) {
    // /T снимает всё дерево, но только от конкретного PID — не по образу и не по порту.
    spawnSync("taskkill", ["/T", "/F", "/PID", String(pid)], { stdio: "inherit" });
  } else {
    for (const c of childPidsPosix(pid).reverse()) {
      try { process.kill(c, "SIGTERM"); } catch { /* мёртв */ }
    }
    try { process.kill(pid, "SIGTERM"); } catch { /* мёртв */ }
  }
}

function serve(cmdArgs) {
  const child = spawn(cmdArgs[0], cmdArgs.slice(1), {
    stdio: "inherit",
    cwd: path.resolve(import.meta.dirname, ".."),
    shell: IS_WIN, // pnpm на Windows лежит за .cmd-обёрткой
  });
  const recordedName = IS_WIN ? "node.exe" : procName(child.pid) || "node";
  fs.writeFileSync(PID_FILE_DEFAULT, `${child.pid}\n${recordedName}\n`, "utf8");
  console.log(`[web-dev-wrapper] dev-сервер запущен (pid ${child.pid}), PID-файл: ${PID_FILE_DEFAULT}`);

  const shutdown = () => {
    console.log("[web-dev-wrapper] останавливаю только своё дерево процессов ...");
    if (child.pid) killTree(child.pid);
    try { fs.unlinkSync(PID_FILE_DEFAULT); } catch { /* уже удалён */ }
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  child.on("exit", (code) => {
    try { fs.unlinkSync(PID_FILE_DEFAULT); } catch { /* уже удалён */ }
    process.exit(code ?? 0);
  });
}

function stop(file) {
  let pid, recorded;
  try {
    ({ pid, name: recorded } = readPidFile(file));
  } catch {
    console.error(`[web-dev-wrapper] нет файла ${file} — нечего останавливать`);
    process.exit(1);
  }
  if (!pid) {
    console.error(`[web-dev-wrapper] некорректный PID в ${file}`);
    process.exit(1);
  }
  const current = procName(pid);
  if (!current) {
    console.error(`[web-dev-wrapper] процесс ${pid} не найден (уже завершён?)`);
    process.exit(1);
  }
  if (recorded && current !== recorded) {
    console.error(
      `[web-dev-wrapper] PID ${pid} занят другим процессом (${current} != ${recorded}) — НЕ убиваю`,
    );
    process.exit(1);
  }
  console.log(`[web-dev-wrapper] останавливаю pid ${pid} (${current}) и его дерево`);
  killTree(pid);
  process.exit(0);
}

const argv = process.argv.slice(2);
if (argv[0] === "--stop") {
  stop(argv[1] ?? PID_FILE_DEFAULT);
} else if (argv.length > 0) {
  serve(argv);
} else {
  console.error("Использование: web-dev-wrapper.mjs <команда ...> | --stop [pid-файл]");
  process.exit(2);
}
