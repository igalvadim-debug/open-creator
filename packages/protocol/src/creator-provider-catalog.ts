export type CreatorProviderKind = 'llm' | 'image' | 'video' | 'tts' | 'transcription';
export type CreatorProviderProtocol = 'openai-compatible' | 'gemini' | 'kling' | 'custom' | 'local';
export type CreatorProviderStatus = 'supported' | 'experimental' | 'planned';
export type CreatorProviderCredential = 'apiKey' | 'accessKey' | 'secretKey' | 'region';

export type CreatorProviderModel = {
  id: string;
  label: string;
  recommended?: boolean;
  capabilities?: readonly string[];
};

export type CreatorProviderCatalogEntry = {
  id: string;
  kind: CreatorProviderKind;
  label: string;
  protocol: CreatorProviderProtocol;
  defaultBaseUrl?: string;
  models: readonly CreatorProviderModel[];
  credentials: readonly CreatorProviderCredential[];
  capabilities?: readonly string[];
  status: CreatorProviderStatus;
};

const entry = (value: CreatorProviderCatalogEntry) => value;

// LOCAL-FIRST: когда включён OPENCREATOR_LOCAL=1, все AI-провайдеры переводятся
// на локальные серверы (llama.cpp / ComfyUI / whisper / piper). Cloud-записи
// ниже остаются только как справочник форматов протоколов и не используются
// в рантайме при локальном режиме.
const LOCAL_MODE = /^(1|true|yes)$/i.test(process.env.OPENCREATOR_LOCAL ?? '');
const LOCAL_LLM_BASE = process.env.LOCAL_LLM_BASE_URL ?? 'http://127.0.0.1:8484/v1';
const LOCAL_COMFY_IMAGE = process.env.COMFY_IMAGE_BASE_URL ?? 'http://127.0.0.1:8291';
const LOCAL_COMFY_VIDEO = process.env.COMFY_VIDEO_BASE_URL ?? 'http://127.0.0.1:8197';

export const localCreatorProviderCatalog: readonly CreatorProviderCatalogEntry[] = [
  entry({ id: 'local-llm', kind: 'llm', label: 'Local LLM (llama.cpp :8484)', protocol: 'openai-compatible', defaultBaseUrl: LOCAL_LLM_BASE, models: [
    { id: 'Qwen3-8B-Q4_K_M.gguf', label: 'Qwen3 8B', recommended: true },
    { id: 'Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf', label: 'Qwen2.5 Coder 7B' },
    { id: 'gemma-3n-E4B-it-QAT-Q4_K_XL.gguf', label: 'Gemma-3n E4B' },
    { id: 'Qwen3-4B-Instruct-2507-Q8_0.gguf', label: 'Qwen3 4B' },
    { id: 'gemma-3-4b-it-qat-q4_0-gguf.gguf', label: 'Gemma-3 4B + vision mmproj' }
  ], credentials: [], capabilities: ['chat', 'translation', 'prompt-enhance', 'agent'], status: 'supported' }),
  entry({ id: 'local-image', kind: 'image', label: 'Local ComfyUI image (:8291)', protocol: 'local', defaultBaseUrl: LOCAL_COMFY_IMAGE, models: [
    { id: 'auto:checkpoints', label: 'Из cw_local_catalog.json (checkpoints)', recommended: true },
    { id: 'auto:diffusion_model_gguf', label: 'GGUF diffusion models' }
  ], credentials: [], capabilities: ['text-to-image', 'image-edit', 'reference-image'], status: 'supported' }),
  entry({ id: 'local-video', kind: 'video', label: 'Local ComfyUI video (:8197)', protocol: 'local', defaultBaseUrl: LOCAL_COMFY_VIDEO, models: [
    { id: 'minimax_h3_fl2va_pruned_w6a8.safetensors', label: 'MiniMax H3 Flash-LV pruned (local GGUF/safetensors)', recommended: true }
  ], credentials: [], capabilities: ['text-to-video', 'image-to-video'], status: 'supported' }),
  entry({ id: 'local-tts', kind: 'tts', label: 'Local TTS (Piper / Coqui XTTS-v2 / F5-TTS)', protocol: 'local', models: [
    { id: 'piper', label: 'Piper (быстрый, .onnx голоса)', recommended: true },
    { id: 'xtts_v2', label: 'Coqui XTTS-v2 (клонирование голоса)' },
    { id: 'f5tts', label: 'F5-TTS' }
  ], credentials: [], capabilities: ['speech-generation', 'voice-preview', 'dubbing'], status: 'supported' }),
  entry({ id: 'local-stt', kind: 'transcription', label: 'Local Whisper (faster-whisper / whisper.cpp)', protocol: 'local', models: [
    { id: 'base', label: 'Whisper base', recommended: true },
    { id: 'small', label: 'Whisper small' },
    { id: 'medium', label: 'Whisper medium' }
  ], credentials: [], capabilities: ['transcribe', 'srt', 'vtt'], status: 'supported' })
];

export const creatorProviderCatalogBase = [
  entry({ id: 'openai', kind: 'llm', label: 'OpenAI', protocol: 'openai-compatible', defaultBaseUrl: 'https://api.openai.com/v1', models: [{ id: 'gpt-5.6-sol', label: 'GPT-5.6 Sol', recommended: true }], credentials: ['apiKey'], status: 'supported' }),
  entry({ id: 'deepseek', kind: 'llm', label: 'DeepSeek', protocol: 'openai-compatible', defaultBaseUrl: 'https://api.deepseek.com', models: [{ id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', recommended: true }, { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash' }, { id: 'deepseek-flash', label: 'DeepSeek Flash' }], credentials: ['apiKey'], status: 'supported' }),
  entry({ id: 'minimax', kind: 'llm', label: 'MiniMax', protocol: 'openai-compatible', defaultBaseUrl: 'https://api.minimax.io', models: [{ id: 'MiniMax-M2.7', label: 'MiniMax M2.7', recommended: true }, { id: 'MiniMax-M2.7-highspeed', label: 'MiniMax M2.7 Highspeed' }, { id: 'MiniMax-M2.5', label: 'MiniMax M2.5' }, { id: 'MiniMax-M2.5-highspeed', label: 'MiniMax M2.5 Highspeed' }], credentials: ['apiKey'], status: 'supported' }),
  entry({ id: 'custom', kind: 'llm', label: 'Custom OpenAI-compatible', protocol: 'custom', models: [], credentials: ['apiKey'], status: 'supported' }),
  entry({ id: 'openai', kind: 'image', label: 'OpenAI', protocol: 'openai-compatible', defaultBaseUrl: 'https://api.openai.com/v1', models: [{ id: 'gpt-image-1', label: 'GPT Image', recommended: true }], credentials: ['apiKey'], capabilities: ['text-to-image', 'image-edit', 'reference-image'], status: 'supported' }),
  entry({ id: 'jimeng', kind: 'image', label: 'Jimeng / Seedream', protocol: 'openai-compatible', defaultBaseUrl: 'https://ark.cn-beijing.volces.com/api/v3', models: [{ id: 'doubao-seedream-4-0-250828', label: 'Seedream 4.0', recommended: true }], credentials: ['apiKey'], capabilities: ['text-to-image'], status: 'supported' }),
  entry({ id: 'kling', kind: 'image', label: 'Kling', protocol: 'kling', defaultBaseUrl: 'https://api-beijing.klingai.com', models: [{ id: 'kling-v2-1', label: 'Kling v2.1', recommended: true }], credentials: ['accessKey', 'secretKey'], capabilities: ['text-to-image'], status: 'supported' }),
  entry({ id: 'gemini', kind: 'image', label: 'Nano Banana / Gemini', protocol: 'gemini', defaultBaseUrl: 'https://generativelanguage.googleapis.com/v1beta', models: [{ id: 'gemini-2.5-flash-image', label: 'Nano Banana', recommended: true }], credentials: ['apiKey'], capabilities: ['text-to-image', 'reference-image'], status: 'supported' }),
  entry({ id: 'codex-native', kind: 'image', label: 'Local Codex image generation', protocol: 'local', models: [], credentials: [], capabilities: ['text-to-image', 'image-edit', 'reference-image'], status: 'experimental' }),
  entry({ id: 'seedance', kind: 'video', label: 'Seedance', protocol: 'openai-compatible', defaultBaseUrl: 'https://ark.cn-beijing.volces.com/api/v3', models: [{ id: 'doubao-seedance-2-5-260628', label: 'Seedance 2.5', recommended: true }], credentials: ['apiKey'], capabilities: ['text-to-video', 'image-to-video'], status: 'supported' }),
  entry({ id: 'kling-video', kind: 'video', label: 'Kling', protocol: 'kling', defaultBaseUrl: 'https://api-beijing.klingai.com', models: [{ id: 'kling-v2-1-master', label: 'Kling v2.1 Master', recommended: true }], credentials: ['accessKey', 'secretKey'], capabilities: ['text-to-video', 'image-to-video'], status: 'supported' }),
  entry({ id: 'veo', kind: 'video', label: 'Veo', protocol: 'gemini', defaultBaseUrl: 'https://generativelanguage.googleapis.com/v1beta', models: [{ id: 'veo-3.1-generate-preview', label: 'Veo 3.1', recommended: true }], credentials: ['apiKey'], capabilities: ['text-to-video', 'image-to-video'], status: 'supported' }),
  entry({ id: 'openai-tts', kind: 'tts', label: 'OpenAI Voice', protocol: 'openai-compatible', defaultBaseUrl: 'https://api.openai.com/v1', models: [{ id: 'gpt-4o-mini-tts', label: 'GPT-4o mini TTS', recommended: true }], credentials: ['apiKey'], capabilities: ['speech-generation', 'voice-preview'], status: 'supported' }),
  entry({ id: 'minimax-tts', kind: 'tts', label: 'MiniMax Voice', protocol: 'openai-compatible', defaultBaseUrl: 'https://api.minimax.io', models: [{ id: 'speech-2.8-hd', label: 'Speech 2.8 HD', recommended: true }], credentials: ['apiKey'], capabilities: ['speech-generation', 'voice-preview'], status: 'supported' }),
  entry({ id: 'aliyun-tts', kind: 'tts', label: 'Alibaba Cloud Voice', protocol: 'openai-compatible', defaultBaseUrl: 'https://dashscope.aliyuncs.com/api/v1', models: [{ id: 'qwen3-tts-flash', label: 'Qwen3 TTS Flash', recommended: true }], credentials: ['apiKey'], capabilities: ['speech-generation', 'voice-preview'], status: 'supported' }),
  entry({ id: 'edge-tts', kind: 'tts', label: 'Edge TTS', protocol: 'custom', models: [], credentials: [], capabilities: ['speech-generation'], status: 'supported' })
];

// Публичный каталог: в локальном режиме (OPENCREATOR_LOCAL=1) — только локальные
// провайдеры; иначе — полная таблица, но с приоритетом локальных записей.
export const creatorProviderCatalog = (LOCAL_MODE
  ? localCreatorProviderCatalog
  : [...localCreatorProviderCatalog, ...creatorProviderCatalogBase]) as readonly CreatorProviderCatalogEntry[];

export const creatorProviderCatalogById = {
  llm: Object.fromEntries(creatorProviderCatalog.filter(item => item.kind === 'llm').map(item => [item.id, item])),
  image: Object.fromEntries(creatorProviderCatalog.filter(item => item.kind === 'image').map(item => [item.id, item]))
} as Record<'llm' | 'image', Record<string, CreatorProviderCatalogEntry>>;

export function creatorProvidersOfKind(kind: CreatorProviderKind): readonly CreatorProviderCatalogEntry[] {
  return creatorProviderCatalog.filter(provider => provider.kind === kind);
}

export function creatorProviderOfKind(
  kind: CreatorProviderKind,
  id: string
): CreatorProviderCatalogEntry | undefined {
  return creatorProviderCatalog.find(provider => provider.kind === kind && provider.id === id);
}
