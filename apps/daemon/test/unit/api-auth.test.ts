import { describe, expect, it } from 'vitest';
import { requireAuth, safeEqual } from '../../src/api/auth.js';

function fakeReply() {
  const reply = {
    statusCode: 0,
    body: undefined as unknown,
    code(c: number) { this.statusCode = c; return this; },
    send(b: unknown) { this.body = b; return this; },
  };
  return reply;
}

describe('safeEqual', () => {
  it('accepts equal strings', () => {
    expect(safeEqual('Bearer secret', 'Bearer secret')).toBe(true);
  });
  it('rejects different strings of same length', () => {
    expect(safeEqual('Bearer secretA', 'Bearer secretB')).toBe(false);
  });
  it('rejects different lengths without throwing', () => {
    expect(safeEqual('a', 'aa')).toBe(false);
  });
});

describe('requireAuth', () => {
  const guard = requireAuth('token123');

  it('passes on the exact bearer token', async () => {
    const reply = fakeReply();
    const result = await guard(
      { headers: { authorization: 'Bearer token123' } } as never,
      reply as never,
    );
    expect(reply.statusCode).toBe(0);
    expect(result).toBeUndefined();
  });

  it('rejects a wrong token with 401', async () => {
    const reply = fakeReply();
    await guard({ headers: { authorization: 'Bearer wrong' } } as never, reply as never);
    expect(reply.statusCode).toBe(401);
    expect((reply.body as { error: { code: string } }).error.code).toBe('UNAUTHORIZED');
  });

  it('rejects a missing header with 401 (no crash on undefined)', async () => {
    const reply = fakeReply();
    await guard({ headers: {} } as never, reply as never);
    expect(reply.statusCode).toBe(401);
  });

  it('rejects non-string array header values with 401', async () => {
    const reply = fakeReply();
    await guard({ headers: { authorization: ['Bearer token123', 'x'] } } as never, reply as never);
    expect(reply.statusCode).toBe(401);
  });
});
