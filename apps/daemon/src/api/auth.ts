import { timingSafeEqual } from 'node:crypto';
import { Buffer } from 'node:buffer';
import type { FastifyReply, FastifyRequest } from 'fastify';

/**
 * Constant-time comparison of two strings. Lengths are compared first
 * (length itself is not secret), then bytes are compared without early
 * exit to rule out timing side channels on the bearer token.
 */
export function safeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return timingSafeEqual(bufA, bufB);
}

export function requireAuth(expectedToken: string) {
  return async function auth(request: FastifyRequest, reply: FastifyReply) {
    const value = request.headers.authorization;
    // LOCAL-FIRST: daemon слушает только 127.0.0.1, но токен всё равно
    // сверяется за константное время — защита от timing-атак с localhost.
    if (typeof value !== 'string' || !safeEqual(value, `Bearer ${expectedToken}`)) {
      return reply.code(401).send({ error: { code: 'UNAUTHORIZED', message: 'Unauthorized' } });
    }
  };
}
