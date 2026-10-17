import type { ImageProvider } from './provider.js';

// LOCAL-FIRST: в режиме OPENCREATOR_LOCAL=1 базовый URL cloud-провайдера
// принудительно заменяется на локальный llama-server :8484 (или COMFY_IMAGE_BASE_URL),
// а fetch защищается local-guard'ом. Cloud при этом не вызывается никогда.
/**
 * Use LOCAL_LLM_BASE_URL or fallback in local mode; otherwise use the supplied
 * base URL, falling back only when it is empty.
 */
function localBaseUrl(baseUrl: string, fallback: string): string {
  if (/^(1|true|yes)$/i.test(process.env.OPENCREATOR_LOCAL ?? '')) {
    return process.env.LOCAL_LLM_BASE_URL ?? fallback;
  }
  return baseUrl || fallback;
}

/**
 * Create a generation-only image provider, selecting its base URL at creation.
 *
 * Local mode uses LOCAL_LLM_BASE_URL or the localhost default; an empty base URL
 * also uses that default outside local mode. Generation returns PNG-labeled
 * bytes from the first base64 item or downloads its URL without host validation.
 * The signal is passed to generation and download requests.
 *
 * The returned generate method rejects reference images, failed HTTP requests,
 * and missing output. Fetch, decoding, and download errors propagate.
 */
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
    /**
     * Return the first generated image as bytes, rejecting reference images,
     * HTTP failures, and missing output; fetch and decoding errors propagate.
     */
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
