import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: {
        ...globals.browser,
        // Injected by Vite's `define` at build time.
        __APP_VERSION__: 'readonly',
      },
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // New in eslint-plugin-react-hooks 7.x (pulled in by the eslint 10 upgrade).
      // Adopt incrementally: warn, not error, so the bump lands green. The flagged
      // data-loading effects / mutation sites are tracked for separate triage.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
      // HMR-only DX rule (not a correctness concern). Several context/primitive
      // files intentionally co-locate a hook or helper with their component;
      // splitting them is churn for no runtime benefit. Keep visible as a warning.
      'react-refresh/only-export-components': 'warn',
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.type='MemberExpression'][callee.property.name='map']",
          message: 'Use safeMap(...) instead of direct .map(...) calls.',
        },
        {
          selector: "OptionalCallExpression[callee.type='OptionalMemberExpression'][callee.property.name='map']",
          message: 'Use safeMap(...) instead of direct .map(...) calls.',
        },
      ],
    },
  },
  {
    files: ['src/utils/safe.js'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
  // Node-context build tooling — not browser code.
  {
    files: ['**/*.config.js', 'scripts/**/*.js'],
    languageOptions: {
      globals: globals.node,
    },
  },
  // Vitest test files run in jsdom with vitest globals.
  {
    files: [
      '**/*.test.{js,jsx}',
      'src/test/**/*.{js,jsx}',
      'src/**/__tests__/**/*.{js,jsx}',
    ],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.vitest,
        ...globals.node,
      },
    },
  },
])
