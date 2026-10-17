import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { describe, expect, it } from 'vitest';

const execute = promisify(execFile);
const repositoryRoot = fileURLToPath(new URL('../../../../', import.meta.url));

describe('local Python services (stdlib unittest)', () => {
  it.each(['clients', 'media', 'generation', 'agent_pipelines', 'stack', 'inventory'])(
    '%s unit tests',
    async suite => {
      const { stderr } = await execute(process.env.PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3'), [
        '-B', '-m', 'unittest', 'discover', '-s', 'tests/local', '-p', `test_${suite}.py`, '-v'
      ], { cwd: repositoryRoot, timeout: 15000, maxBuffer: 1024 * 1024 });
      expect(stderr).toMatch(/Ran [1-9]\d* tests? in/);
    },
    20000
  );
});
