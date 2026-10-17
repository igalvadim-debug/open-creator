import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => {
  vi.resetModules();
  for (const key of ['OPENCREATOR_LOCAL', 'LOCAL_LLM_BASE_URL', 'COMFY_IMAGE_BASE_URL', 'COMFY_VIDEO_BASE_URL']) {
    vi.stubEnv(key, undefined);
  }
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('local creator provider catalog', () => {
  it.each(['1', 'true', 'YES', 'TrUe'])('exposes only credential-free local providers for %s', async flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    const catalog = await import('./creator-provider-catalog.js');
    expect(catalog.creatorProviderCatalog.map(item => item.id)).toEqual([
      'local-llm', 'local-image', 'local-video', 'local-tts', 'local-stt'
    ]);
    expect(catalog.creatorProviderCatalog.every(item => item.credentials.length === 0 && item.status === 'supported')).toBe(true);
    expect(catalog.creatorProviderCatalogById.llm.openai).toBeUndefined();
    expect(catalog.creatorProviderCatalogById.image.openai).toBeUndefined();
    for (const kind of ['llm', 'image', 'video', 'tts', 'transcription'] as const) {
      const providers = catalog.creatorProvidersOfKind(kind);
      expect(providers).toHaveLength(1);
      expect(providers[0]!.models.some(model => model.recommended)).toBe(true);
      expect(catalog.creatorProviderOfKind(kind, providers[0]!.id)).toBe(providers[0]);
    }
    expect(catalog.creatorProviderOfKind('llm', 'local-image')).toBeUndefined();
  });

  it.each([undefined, '0', 'false', 'no', 'trueish'])('puts local providers first while retaining cloud providers for %j', async flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    const catalog = await import('./creator-provider-catalog.js');
    expect(catalog.creatorProviderCatalog.slice(0, 5)).toEqual(catalog.localCreatorProviderCatalog);
    expect(catalog.creatorProviderCatalog.slice(5)).toEqual(catalog.creatorProviderCatalogBase);
    expect(catalog.creatorProviderCatalogById.llm.openai?.defaultBaseUrl).toBe('https://api.openai.com/v1');
    expect(catalog.creatorProviderCatalogById.image['local-image']?.defaultBaseUrl).toBe('http://127.0.0.1:8291');
  });

  it('uses independent endpoint overrides for local LLM, image and video providers', async () => {
    vi.stubEnv('LOCAL_LLM_BASE_URL', 'http://localhost:9000/v1');
    vi.stubEnv('COMFY_IMAGE_BASE_URL', 'http://192.168.1.2:9001');
    vi.stubEnv('COMFY_VIDEO_BASE_URL', 'http://192.168.1.3:9002');
    const { creatorProviderOfKind: provider } = await import('./creator-provider-catalog.js');
    expect(provider('llm', 'local-llm')?.defaultBaseUrl).toBe('http://localhost:9000/v1');
    expect(provider('image', 'local-image')?.defaultBaseUrl).toBe('http://192.168.1.2:9001');
    expect(provider('video', 'local-video')?.defaultBaseUrl).toBe('http://192.168.1.3:9002');
  });
});
