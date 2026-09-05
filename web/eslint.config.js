import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // Сгенерированное и собранное не проверяем: править его нельзя, а ругань в нём
  // заглушила бы настоящие замечания.
  { ignores: ['dist', 'node_modules', 'src/api/schema.d.ts', 'openapi.json'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    files: ['**/*.config.{ts,js}', 'src/test/**'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  {
    // Сквозные проверки живут в Node (файлы, подпроцессы, журнал стенда) и
    // заодно исполняют куски кода в браузере — поэтому оба набора глобальных.
    files: ['e2e/**/*.ts'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
)
