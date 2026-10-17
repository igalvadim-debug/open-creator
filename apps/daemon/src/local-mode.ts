export function isLocalMode(env: NodeJS.ProcessEnv): boolean {
  return /^(1|true|yes)$/i.test(env.OPENCREATOR_LOCAL ?? '');
}
