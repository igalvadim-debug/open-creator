# open-creator LOCAL — локализация на локальные модели

Все AI-функции open-creator (LLM/агенты, перевод, дубляж/TTS, STT, embeddings/RAG)
работают через **local-stack** (llama.cpp + LanceDB + MCP). В рантайме — **0 обращений
к внешним AI API**. Сеть нужна только при первичной установке моделей
(`local-stack/setup_models.py`). Image/video-генерация через ComfyUI вынесена в
отдельную задачу (`cwbuilder-docs/`) и здесь не затрагивается.

## Установка (Windows)

Двойной клик по **`install.bat`** (или `.\install.bat` в cmd) — скрипт найдёт CPython
(`py -3.12` → `py -3` → `python`) и вызовет `install.py`, который:
создаст `./venv`, поставит `requirements.txt`, скачает GGUF-модели в `./local-stack/models/`,
выполнит `corepack enable && pnpm install` и сгенерирует `start.bat`.
Всё остаётся локально в папке репозитория. После установки `install.bat` предложит
запустить стек сразу (`start.bat` — стек + веб-интерфейс http://127.0.0.1:19861/).

Явный запуск без bat-обёртки: `"C:\путь\к\python.exe" install.py [--python <python.exe>]`.

## Запуск

```bash
# 1. Поднять local-stack (LLM :8484, embeddings :8512, MCP :8001, repomapper :8002, lancedb :8003)
cd local-stack && python setup_models.py   # только при первой установке (сеть)
python start.py                            # Windows — табы, Linux — tmux

# 2. Проверить локальность (ожидается: все сервисы GREEN, внешних вызовов нет)
python check_local.py

# 3. Настроить daemon: cp .env.example .env  (OPENCREATOR_LOCAL=1)

# 4. Pipeline «скачать -> транскрибировать -> перевести -> озвучить -> собрать»
python pipelines/download_translate_dub.py --url <video_url> --dst ru
```

## Таблица аудита: функция → внешний сервис → локальная замена

| Функция | Внешний сервис (найдено в коде) | Локальная замена | Где переключено |
|---|---|---|---|
| LLM / агенты Codex | `api.openai.com/v1` (`apps/daemon/src/codex/local-provider.ts:79`) | llama-server `http://127.0.0.1:8484/v1`, модель `Qwen3-8B-Q4_K_M.gguf` | `OPENCREATOR_LOCAL=1` → early-return в `readLocalCodexProvider`; `opencode.json` |
| LLM (stickman-скрипты) | fallback `https://api.openai.com/v1` (`script-generator.ts:39`) | `:8484/v1` | LOCAL-FIRST ветка env `LOCAL_LLM_BASE_URL` |
| LLM (раскадровка) | fallback `api.openai.com` (`storyboard-generator.ts`) | `:8484/v1` | LOCAL-FIRST ветка (добавлена) |
| LLM (content-executor) | fallback `api.openai.com` + обязательный apiKey (`content-executor.ts`) | `:8484/v1`, ключ не требуется | LOCAL-FIRST ветка (добавлена) |
| LLM (clip-analyzer) | fallback `api.openai.com` (`analyzer.ts:52`) | `:8484/v1` | LOCAL-FIRST ветка |
| Creator services (upstream) | default `https://api.openai.com/v1/{resource}` (`upstream-fetch.ts:65`) | `:8484/v1/{resource}` при пустом baseUrl | LOCAL-FIRST ветка (добавлена) |
| Cloud-TTS OpenAI/Aliyun/Volcengine/MiniMax | `api.openai.com/v1/audio/speech`, dashscope, volcengine, minimax (`krillin/tts-service.ts`) | локальный TTS: llama.cpp `/v1/audio/speech` (:8484) либо Piper/Coqui XTTS-v2/F5-TTS (`core/tts_client.py`) | перехват в `providerFetch` по `OPENCREATOR_LOCAL=1` (добавлен) |
| Cloud-STT (Whisper API / AssemblyAI / Volcengine ASR) | whisper REST, volcengine STT | faster-whisper / whisper.cpp локально (`core/stt_client.py`), модель base/small/medium по VRAM; выход srt/vtt/txt | `core/stt_client.py`, `LOCAL_WHISPER_MODEL` |
| Перевод (DeepL / Google Translate) | — (в текущем коде cloud-переводчиков не найдено) | локальная LLM :8484 (`core/translation.py`), промпт `config/prompts/translation.txt`, языки ru/de/en | config.local.json `translation.engine=local_llm` |
| Embeddings / RAG | cloud embedding API | llama-server :8512 (`embeddinggemma-300m-qat-Q8_0.gguf`, фолбэк `bge-m3-Q8_0.gguf`), батчи по 8, чанки 30 строк, sha1+mtime-кэш | `core/embedding_client.py`, `local-stack/lancedb_mcp/db_http.py` |
| Векторная база | облачные вектор-БД | LanceDB `./lancedb_context`, таблица `project_code_local`, HTTP :8003 | local-stack (не трогать) |
| Поиск по коду (MCP) | — | MCP :8001 `search_code` / `list_indexed_files` / `reindex` (`local-stack/lancedb_mcp/server_local.py`); RepoMapper AST :8002 | `agents/local_agent.py`, `opencode.json` mcp |
| Free-tier fallback эмбеддингов | внешний free API | **ВЫКЛЮЧЕН**: `ALLOW_FREE_TIER=0` (default в `local-stack/config.py:75`); попытка вызова → RuntimeError | `.env.example` |
| Video downloading | yt-dlp (не AI-модель) | оставлен как есть; добавлен pipeline download→STT→translate→TTS→ffmpeg | `core/video_download.py`, `pipelines/download_translate_dub.py` |
| Anthropic / ElevenLabs / Replicate | не обнаружены в коде | n/a — grep даёт 0 активных вызовов | — |
| Image/Video generation | Jimeng/Kling/Seedance/Veo и пр. | вне scope задачи; локально — ComfyUI :8291/:8197 через `cwbuilder-docs` | (см. cwbuilder-docs) |

## Как это работает

- **Python-слой** (`core/`, `agents/`, `pipelines/`) использует local-stack как ядро:
  модуль `local-stack/llama_client.py` содержит политику `assert_local` — любой URL,
  отличный от `127.0.0.1`/`localhost`, вызывает ошибку. Код local-stack не переписан.
- **TypeScript-слой (daemon)**: флаг окружения `OPENCREATOR_LOCAL=1`:
  - `packages/protocol/src/creator-provider-catalog.ts` отдаёт только локальных провайдеров;
  - `apps/daemon/src/codex/local-provider.ts` ведёт агентов на `:8484/v1`;
  - `apps/daemon/src/env-local.ts` обнуляет cloud-ключи Volcengine;
  - `apps/daemon/src/local-guard.ts` — guard `fetch`, блокирующий не-локальные AI-хосты;
  - fallback-URL во всех stickman/analyzer/upstream-модулях перекрыты LOCAL-FIRST ветками.
- **API-ключи не нужны**: llama-server их не проверяет, клиент шлёт `Bearer local`.

## Проверка локальности

```bash
grep -rn "api.openai.com\|api.anthropic.com\|api.elevenlabs.io\|api.deepl.com" \
  core agents pipelines config local-stack            # 0 результатов
python local-stack/check_local.py                      # все порты GREEN, внешних вызовов 0
```

Cloud-эндпоинты остаются в репозитории только как: (а) reference-значения в
нелокальном режиме (флаг выключен), (б) placeholder'ы UI/prompt-подсказок,
(в) тесты старого cloud-поведения. При `OPENCREATOR_LOCAL=1` недостижимы.

## Порты

| Сервис | Порт |
|---|---|
| LLM (llama.cpp, OpenAI-совместимый `/v1`) | 8484 |
| Embeddings (`/v1/embeddings`) | 8512 |
| MCP (LanceDB search_code/list/reindex) | 8001 |
| RepoMapper (AST, без LLM) | 8002 |
| LanceDB HTTP | 8003 |
| ComfyUI image / video (вне scope, cwbuilder-docs) | 8291 / 8197 |

## Структура

```
open-creator/
├── local-stack/        # ядро: start.py, config.py, llama_client.py, lancedb_mcp/, RepoMapper/ (не трогать)
├── core/               # llm_client, embedding_client, stt_client, tts_client, translation, video_download
├── agents/local_agent.py       # Codex-подобный агент на :8484 + MCP-инструменты
├── config/config.local.json    # голоса TTS, языки перевода, пути моделей (все относительные)
├── config/prompts/translation.txt
├── pipelines/download_translate_dub.py
├── opencode.json       # все провайдеры/MCP -> 127.0.0.1
└── requirements.txt    # yt-dlp, faster-whisper, piper-tts, lancedb — только локальные движки
```
