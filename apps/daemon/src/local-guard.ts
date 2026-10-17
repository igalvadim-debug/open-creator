// LOCAL-FIRST guard (open-creator localization)
//
// Плагин fetch, запрещающий обращения к внешним AI API в рантайме.
// Подключается в bootstrap daemon'а:
//   import { installLocalOnlyFetch } from './local-guard.js';
//   if (process.env.OPENCREATOR_LOCAL === '1') installLocalOnlyFetch();
//
// Разрешены: 127.0.0.1 / localhost / ::1 / 0.0.0.0 и приватные подсети
// (локальные ComfyUI/llama.cpp/TTS серверы). Всё остальное — ошибка с
// явным сообщением о политике локальности.

const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '::1', '0.0.0.0']);

/**
 * Check the fetch guard's URL rules. Non-HTTP(S) schemes are accepted;
 * HTTP(S) hosts must match the local set or private-address prefix patterns.
 * Malformed URL strings return false. No DNS resolution is performed.
 */
export function isLocalUrl(raw: string | URL): boolean {
  try {
    const u = typeof raw === 'string' ? new URL(raw) : raw;
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return true; // file:/data:/blob:
    const h = u.hostname.replace(/^\[|\]$/g, '');
    if (LOCAL_HOSTS.has(h)) return true;
    // 10.x, 192.168.x, 172.16-31.x — домашние GPU-боксы тоже «локальные»
    if (/^10\./.test(h) || /^192\.168\./.test(h) || /^172\.(1[6-9]|2\d|3[01])\./.test(h)) return true;
    return false;
  } catch {
    return false;
  }
}

export class ExternalApiBlockedError extends Error {
  /** Create a policy error identifying the rejected URL. */
  constructor(url: string) {
    super(`OPENCREATOR_LOCAL=1: внешний AI API запрещён политикой локальности (${url})`);
    this.name = 'ExternalApiBlockedError';
  }
}

/**
 * Replace the target object's fetch with a guard on the initial request URL.
 * Use globalThis.fetch when the target has no fetch. This does not inspect
 * redirect destinations or validate hosts accepted by prefix patterns.
 *
 * The installed fetch rejects disallowed URLs with ExternalApiBlockedError;
 * errors from the captured fetch propagate.
 */
export function installLocalOnlyFetch(globalObj: { fetch?: unknown } = globalThis as never): void {
  const original = (globalObj.fetch ?? globalThis.fetch) as typeof fetch;
  const guarded: typeof fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (!isLocalUrl(url)) throw new ExternalApiBlockedError(url);
    return original(input as RequestInfo, init);
  };
  globalObj.fetch = guarded;
}
