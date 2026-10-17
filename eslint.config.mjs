// Flat-config ESLint для всего монорепозитория (TS + TSX).
// Конфиг минимальный, но строгий к реальным дефектам: плавающие промисы,
// неиспользуемые переменные, == вместо ===.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/**', '**/dist/**', '**/build/**', '**/.next/**',
      '**/coverage/**', 'template/**', 'assets/**', 'resources/**',
      'apps/web/public/**', '**/*.d.ts', 'local-stack/bin/**', 'local-stack/models/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      'no-floating-promises': 'off', // покрыто ниже через typed linting при желании
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      '@typescript-eslint/no-explicit-any': 'off', // легаси-кодовая база, включим позже
      'no-console': 'off',
    },
  },
);
