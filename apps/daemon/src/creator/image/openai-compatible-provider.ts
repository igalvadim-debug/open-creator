import type { ImageProvider } from './provider.js';

// LOCAL-FIRST: в режиме OPENCREATOR_LOCAL=1 базовый URL cloud-провайдера
// принудительно заменяется на локальный llama-server :8484 (или COMFY_IMAGE_BASE_URL),
// а fetch защищается local-guard'ом. Cloud при этом не вызывается никогда.
function localBaseUrl(baseUrl: string, fallback: string): string {
  if (/^(1|true|yes)$/i.test(process.env.OPENCREATOR_LOCAL ?? '')) {
    return process.env.LOCAL_LLM_BASE_URL ?? fallback;
  }
  return baseUrl || fallback;
}

export function createOpenAiCompatibleImageProvider(input: {
  baseUrl: string;
  apiKey: string;
  model: string;
  fetchImpl?: typeof fetch;
}): ImageProvider {
  const fetchImpl = input.fetchImpl ?? fetch;
  const baseUrl = localBaseUrl(input.baseUrl, 'http://127.0.0.1:8484/v1');
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
