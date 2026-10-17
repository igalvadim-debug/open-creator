import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExternalApiBlockedError, installLocalOnlyFetch, isLocalUrl } from '../../src/local-guard.js';

afterEach(() => vi.unstubAllGlobals());

describe('local URL policy', () => {
  it.each([
    'http://localhost:8484/v1', 'https://127.0.0.1/v1', 'http://[::1]:8484',
    'http://0.0.0.0', 'http://10.0.0.1', 'http://192.168.255.254',
    'http://172.16.0.1', 'http://172.31.255.254', 'file:///tmp/image.png', 'data:text/plain,local'
  ])('allows %s', url => {
    expect(isLocalUrl(url)).toBe(true);
    expect(isLocalUrl(new URL(url))).toBe(true);
  });

  it.each([
    'https://api.openai.com/v1', 'http://172.15.255.255', 'http://172.32.0.1',
    'http://192.169.0.1', 'http://11.0.0.1', 'http://localhost.example.test',
    'http://10.external.example.test', 'http://192.168.external.example.test',
    'http://localhost@external.example.test', 'http://external.example.test/127.0.0.1',
    '/relative', '', 'not a URL'
  ])('rejects %j', url => expect(isLocalUrl(url)).toBe(false));
});

describe('local fetch guard', () => {
  it.each([
    'http://localhost:8484/v1/models', new URL('http://localhost:8484/v1/models'),
    new Request('http://localhost:8484/v1/models')
  ])('forwards local fetch inputs and init unchanged (%s)', async input => {
    const response = new Response('local');
    const original = vi.fn<typeof fetch>().mockResolvedValue(response);
    const target = { fetch: original as typeof fetch };
    const init = { headers: { 'x-test': 'local' }, signal: new AbortController().signal };
    installLocalOnlyFetch(target);
    await expect(target.fetch(input, init)).resolves.toBe(response);
    expect(original).toHaveBeenCalledExactlyOnceWith(input, init);
  });

  it.each([
    'https://external.example.test', new URL('https://external.example.test'),
    new Request('https://external.example.test')
  ])('blocks external inputs before dispatch (%s)', async input => {
    const original = vi.fn<typeof fetch>();
    const target = { fetch: original as typeof fetch };
    installLocalOnlyFetch(target);
    await expect(target.fetch(input)).rejects.toMatchObject({
      name: 'ExternalApiBlockedError', message: expect.stringContaining('OPENCREATOR_LOCAL=1')
    });
    expect(original).not.toHaveBeenCalled();
  });

  it('uses global fetch when the target has no fetch implementation', async () => {
    const original = vi.fn<typeof fetch>().mockResolvedValue(new Response('ok'));
    vi.stubGlobal('fetch', original);
    const target: { fetch?: typeof fetch } = {};
    installLocalOnlyFetch(target);
    await target.fetch!('http://127.0.0.1');
    expect(original).toHaveBeenCalledOnce();
  });

  it('preserves downstream failures', async () => {
    const error = new TypeError('connection refused');
    const target = { fetch: vi.fn<typeof fetch>().mockRejectedValue(error) as typeof fetch };
    installLocalOnlyFetch(target);
    await expect(target.fetch('http://localhost')).rejects.toBe(error);
    expect(new ExternalApiBlockedError('https://external.example.test')).toBeInstanceOf(Error);
  });
});
