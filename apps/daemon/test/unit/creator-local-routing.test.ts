import { createDefaultCreatorServicesConfig } from '@opencreator/protocol';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { openAiCompatibleEndpoint } from '../../src/creator-services/upstream-fetch.js';
import { analyzeClips } from '../../src/creator/clip/analyzer.js';
import { createOpenAiCompatibleImageProvider } from '../../src/creator/image/openai-compatible-provider.js';
import { createStickmanConfiguredCompletion } from '../../src/creator/stickman/content-executor.js';
import { generateStickmanScript } from '../../src/creator/stickman/script-generator.js';
import { generateStickmanStoryboard } from '../../src/creator/stickman/storyboard-generator.js';

const localBase = 'http://127.0.0.1:8484/v1';
const cloudBase = 'https://cloud.example.test/v1';
const segment = { id: 's1', narration: 'A fact', visualPrompt: 'A stickman', durationSeconds: 5 };
const script = { title: 'Facts', segments: [segment] };
const shots = [{ segmentId: 's1', imagePrompt: 'A stickman', motion: 'static' }];
const connection = { baseUrl: cloudBase, apiKey: 'test-key', model: 'test-model' };
const candidate = {
  id: 'clip-1', title: 'A fact', start: 0, end: 20, transcript: 'A fact', reason: 'Self-contained',
  scores: { hook: 80, information: 90, emotion: 70, completeness: 90 }
};
const completionResponse = (value: unknown) => new Response(JSON.stringify({
  choices: [{ message: { content: JSON.stringify(value) } }]
}));

beforeEach(() => {
  vi.stubEnv('OPENCREATOR_LOCAL', undefined);
  vi.stubEnv('LOCAL_LLM_BASE_URL', undefined);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('creator upstream endpoint defaults', () => {
  it.each(['1', 'TRUE', 'yes'])('uses the local default only for an empty base (%s)', flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    expect(openAiCompatibleEndpoint('  ', 'chat/completions').href).toBe(`${localBase}/chat/completions`);
    expect(openAiCompatibleEndpoint(cloudBase, 'models').href).toBe(`${cloudBase}/models`);
  });

  it('strips trailing slashes from a custom local fallback', () => {
    vi.stubEnv('OPENCREATOR_LOCAL', '1');
    vi.stubEnv('LOCAL_LLM_BASE_URL', 'http://localhost:9000/v1///');
    expect(openAiCompatibleEndpoint('', 'embeddings').href).toBe('http://localhost:9000/v1/embeddings');
  });

  it.each([undefined, '0', 'false', 'trueish'])('preserves the cloud fallback when local mode is disabled (%j)', flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    vi.stubEnv('LOCAL_LLM_BASE_URL', localBase);
    expect(openAiCompatibleEndpoint('', 'models').href).toBe('https://api.openai.com/v1/models');
  });
});

const llmCallers = [
  {
    name: 'clip analysis', response: { candidates: [candidate] }, expected: [candidate],
    call: (fetchImpl: typeof fetch) => analyzeClips({
      ...connection, transcript: 'A transcript', duration: 30, focus: 'balanced',
      minDuration: 10, maxDuration: 30, count: 1, fetchImpl
    })
  },
  {
    name: 'script generation', response: script, expected: script,
    call: (fetchImpl: typeof fetch) => generateStickmanScript({ ...connection, topic: 'Facts', targetDurationSeconds: 5, fetchImpl })
  },
  {
    name: 'storyboard generation', response: { shots }, expected: shots,
    call: (fetchImpl: typeof fetch) => generateStickmanStoryboard({ ...connection, style: 'minimal', characterPrompt: 'stickman', segments: [segment], fetchImpl })
  }
];

describe.each(llmCallers)('$name local routing', caller => {
  it.each(['1', 'true', 'YES'])('overrides a configured cloud endpoint in local mode (%s)', async flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(completionResponse(caller.response));
    await expect(caller.call(fetchImpl)).resolves.toEqual(caller.expected);
    expect(fetchImpl).toHaveBeenCalledExactlyOnceWith(`${localBase}/chat/completions`, expect.objectContaining({ method: 'POST' }));
    expect(JSON.parse(String(fetchImpl.mock.calls[0]![1]!.body))).toMatchObject({ model: 'test-model' });
  });

  it('honors the local endpoint override', async () => {
    vi.stubEnv('OPENCREATOR_LOCAL', '1');
    vi.stubEnv('LOCAL_LLM_BASE_URL', 'http://localhost:9000/v1');
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(completionResponse(caller.response));
    await caller.call(fetchImpl);
    expect(fetchImpl.mock.calls[0]![0]).toBe('http://localhost:9000/v1/chat/completions');
  });

  it('keeps configured routing with local mode disabled', async () => {
    vi.stubEnv('OPENCREATOR_LOCAL', 'false');
    vi.stubEnv('LOCAL_LLM_BASE_URL', localBase);
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(completionResponse(caller.response));
    await caller.call(fetchImpl);
    expect(fetchImpl.mock.calls[0]![0]).toBe(`${cloudBase}/chat/completions`);
  });

  it('propagates a local connection failure without a cloud retry', async () => {
    vi.stubEnv('OPENCREATOR_LOCAL', '1');
    const error = new TypeError('local server unavailable');
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(error);
    await expect(caller.call(fetchImpl)).rejects.toBe(error);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});

describe('local image provider', () => {
  it.each(['1', 'true', 'YES'])('uses the local server and decodes generated image bytes (%s)', async flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    const bytes = Buffer.from('synthetic image');
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ data: [{ b64_json: bytes.toString('base64') }] })));
    const signal = new AbortController().signal;
    const provider = createOpenAiCompatibleImageProvider({ ...connection, fetchImpl });
    await expect(provider.generate({ prompt: 'A tree', ratio: '9:16' }, signal)).resolves.toEqual({ bytes, mimeType: 'image/png' });
    expect(fetchImpl).toHaveBeenCalledExactlyOnceWith(`${localBase}/images/generations`, expect.objectContaining({ signal }));
    expect(JSON.parse(String(fetchImpl.mock.calls[0]![1]!.body))).toMatchObject({ prompt: 'A tree', size: '1024x1536', model: 'test-model' });
  });

  it('honors a custom local endpoint and removes its trailing slash', async () => {
    vi.stubEnv('OPENCREATOR_LOCAL', 'yes');
    vi.stubEnv('LOCAL_LLM_BASE_URL', 'http://localhost:9000/v1/');
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('{}'));
    const provider = createOpenAiCompatibleImageProvider({ ...connection, fetchImpl });
    await expect(provider.generate({ prompt: 'Tree', ratio: '1:1' }, new AbortController().signal)).rejects.toThrow('image_provider_invalid_response');
    expect(fetchImpl.mock.calls[0]![0]).toBe('http://localhost:9000/v1/images/generations');
  });

  it('retains an explicit cloud endpoint when local mode is disabled', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 503 }));
    const provider = createOpenAiCompatibleImageProvider({ ...connection, fetchImpl });
    await expect(provider.generate({ prompt: 'Tree', ratio: '1:1' }, new AbortController().signal)).rejects.toThrow('HTTP 503');
    expect(fetchImpl).toHaveBeenCalledExactlyOnceWith(`${cloudBase}/images/generations`, expect.anything());
  });
});

describe('configured stickman completion in local mode', () => {
  it.each([undefined, 'http://localhost:9000/v1'])('permits a missing API key and uses local routing (%j)', async base => {
    vi.stubEnv('OPENCREATOR_LOCAL', '1');
    vi.stubEnv('LOCAL_LLM_BASE_URL', base);
    const config = createDefaultCreatorServicesConfig();
    config.llm = { ...config.llm, source: 'custom', apiKey: '', baseUrl: cloudBase, model: 'local-model' };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(completionResponse({ title: 'Local' }));
    vi.stubGlobal('fetch', fetchMock);
    const signal = new AbortController().signal;
    const complete = createStickmanConfiguredCompletion({ configStore: { read: async () => config }, context: { jobId: 'job', projectId: 'project', cwd: process.cwd() } });
    await expect(complete({ stageId: 'source-brief', prompt: 'Return JSON', signal })).resolves.toEqual({ title: 'Local' });
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(`${base ?? localBase}/chat/completions`, expect.objectContaining({ signal }));
    expect(JSON.parse(String(fetchMock.mock.calls[0]![1]!.body))).toMatchObject({ model: 'local-model', messages: [{ role: 'user', content: 'Return JSON' }] });
  });

  it('keeps the Codex completion path when that source is selected', async () => {
    vi.stubEnv('OPENCREATOR_LOCAL', '1');
    const config = createDefaultCreatorServicesConfig();
    config.llm.source = 'codex';
    const codexCompleteJson = vi.fn().mockResolvedValue({ title: 'Codex' });
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
    const complete = createStickmanConfiguredCompletion({ configStore: { read: async () => config }, codexCompleteJson, context: { jobId: 'job', projectId: 'project', cwd: process.cwd() } });
    await expect(complete({ stageId: 'source-brief', prompt: 'JSON', signal: new AbortController().signal })).resolves.toEqual({ title: 'Codex' });
    expect(codexCompleteJson).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
