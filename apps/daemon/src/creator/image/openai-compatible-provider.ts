import type { ImageProvider } from './provider.js';
import { LocalCodexProviderError } from '../../codex/local-provider.js';

// LOCAL-FIRST: в режиме OPENCREATOR_LOCAL=1 генерация изображений уходит
// строго на ComfyUI (COMFY_IMAGE_BASE_URL). Локальный llama.cpp
// (LOCAL_LLM_BASE_URL) умеет только текст, поэтому для картинок он не
// используется никогда. В облачном режиме по умолчанию возвращается
// стандартный URL OpenAI.
const DEFAULT_CLOUD_IMAGE_BASE_URL = 'https://api.openai.com/v1';

function localImageBaseUrl(): string {
  const comfyBaseUrl = (process.env.COMFY_IMAGE_BASE_URL ?? '').trim();
  if (comfyBaseUrl.length === 0) {
    throw new LocalCodexProviderError(
      'Image generation is unavailable in local mode: set COMFY_IMAGE_BASE_URL to a running ComfyUI server (the local llama.cpp endpoint only supports text).'
    );
  }
  return comfyBaseUrl.replace(/\/+$/, '');
}

function resolveImageBaseUrl(baseUrl: string): string {
  if (/^(1|true|yes)$/i.test(process.env.OPENCREATOR_LOCAL ?? '')) {
    // Никаких LOCAL_LLM_BASE_URL / Qwen3-8B для картинок — только ComfyUI.
    return localImageBaseUrl();
  }
  return baseUrl || DEFAULT_CLOUD_IMAGE_BASE_URL;
}

export function createOpenAiCompatibleImageProvider(input: {
  baseUrl: string;
  apiKey: string;
  model: string;
  fetchImpl?: typeof fetch;
}): ImageProvider {
  const fetchImpl = input.fetchImpl ?? fetch;
  const baseUrl = resolveImageBaseUrl(input.baseUrl);
  return {
    id: 'openai-compatible',
    capabilities: { generate: true, edit: false },
    async generate(request, signal) {
      if (request.referenceImage !== undefined) throw new Error('unsupported_capability: reference image editing');
      const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/images/generations`, {
        method: 'POST',
        signal,
        headers: { authorization: `Bearer ${input.apiKey}`, 'content-type': 'application/json' },
        body: JSON.stringify({
          model: input.model,
          prompt: request.prompt,
          size: request.ratio === '16:9' ? '1536x1024' : request.ratio === '9:16' ? '1024x1536' : '1024x1024',
          response_format: 'b64_json'
        })
      });
      if (!response.ok) throw new Error(`image_provider_failed: HTTP ${response.status}`);
      const payload = await response.json() as { data?: Array<{ b64_json?: string; url?: string }> };
      const item = payload.data?.[0];
      if (item?.b64_json) return { bytes: Buffer.from(item.b64_json, 'base64'), mimeType: 'image/png' };
      if (item?.url) {
        const download = await fetchImpl(item.url, { signal });
        if (!download.ok) throw new Error('image_provider_download_failed');
        return { bytes: Buffer.from(await download.arrayBuffer()), mimeType: 'image/png' };
      }
      throw new Error('image_provider_invalid_response');
    }
  };
}
