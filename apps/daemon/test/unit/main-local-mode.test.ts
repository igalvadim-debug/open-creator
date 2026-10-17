import { afterEach, describe, expect, it, vi } from 'vitest';
import { installLocalOnlyFetch } from '../../src/local-guard.js';

vi.mock('../../src/local-guard.js', () => ({ installLocalOnlyFetch: vi.fn() }));
vi.mock('../../src/security/token.js', () => ({
  createRuntimeToken: () => { throw new Error('Stop after fetch guard setup'); }
}));

const originalExitCode = process.exitCode;
afterEach(() => {
  process.exitCode = originalExitCode;
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.resetModules();
});

describe('daemon local-mode startup', () => {
  it.each(['1', 'true', 'yes', 'TrUe'])('installs the fetch guard before startup (%s)', async flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    vi.spyOn(console, 'log').mockImplementation(() => undefined);
    await import('../../src/main.js');
    expect(installLocalOnlyFetch).toHaveBeenCalledExactlyOnceWith();
  });

  it.each([undefined, '0', 'false', 'no', 'trueish'])('leaves fetch unchanged with local mode disabled (%j)', async flag => {
    vi.stubEnv('OPENCREATOR_LOCAL', flag);
    vi.spyOn(console, 'log').mockImplementation(() => undefined);
    await import('../../src/main.js');
    expect(installLocalOnlyFetch).not.toHaveBeenCalled();
  });
});
