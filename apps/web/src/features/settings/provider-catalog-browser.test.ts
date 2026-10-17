import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => {
  vi.resetModules();
  for (const key of ['OPENCREATOR_LOCAL', 'LOCAL_LLM_BASE_URL', 'COMFY_IMAGE_BASE_URL', 'COMFY_VIDEO_BASE_URL']) {
    vi.stubEnv(key, undefined);
    vi.stubEnv(`VITE_${key}`, undefined);
  }
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('browser provider catalog configuration', () => {
  it.each(['1', 'true', 'yes'])('reads browser settings when daemon settings are absent (%s)', async flag => {
    vi.stubEnv('VITE_OPENCREATOR_LOCAL', flag);
    vi.stubEnv('VITE_LOCAL_LLM_BASE_URL', 'http://localhost:9100/v1');
    vi.stubEnv('VITE_COMFY_IMAGE_BASE_URL', 'http://localhost:9101');
    vi.stubEnv('VITE_COMFY_VIDEO_BASE_URL', 'http://localhost:9102');
    const catalog = await import('@opencreator/protocol');
    expect(catalog.creatorProviderCatalogById.llm.openai).toBeUndefined();
    expect(catalog.creatorProviderCatalogById.llm['local-llm']?.defaultBaseUrl).toBe('http://localhost:9100/v1');
    expect(catalog.creatorProviderCatalogById.image['local-image']?.defaultBaseUrl).toBe('http://localhost:9101');
    expect(catalog.creatorProviderOfKind('video', 'local-video')?.defaultBaseUrl).toBe('http://localhost:9102');
  });

  it('preserves daemon settings ahead of browser defaults', async () => {
    vi.stubEnv('OPENCREATOR_LOCAL', 'true');
    vi.stubEnv('VITE_OPENCREATOR_LOCAL', 'false');
    for (const key of ['LOCAL_LLM_BASE_URL', 'COMFY_IMAGE_BASE_URL', 'COMFY_VIDEO_BASE_URL']) {
      vi.stubEnv(key, 'http://192.168.1.2:9000');
      vi.stubEnv(`VITE_${key}`, 'http://localhost:9100');
    }
    const catalog = await import('@opencreator/protocol');
    expect(catalog.creatorProviderCatalogById.llm.openai).toBeUndefined();
    for (const kind of ['llm', 'image', 'video'] as const) {
      expect(catalog.creatorProvidersOfKind(kind)[0]?.defaultBaseUrl).toBe('http://192.168.1.2:9000');
    }
  });
});
