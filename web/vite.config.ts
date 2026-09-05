import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import obfuscator from 'rollup-plugin-obfuscator'
import { defineConfig } from 'vitest/config'

// Порт службы берётся из окружения, чтобы параллельные запуски не толкались,
// а по умолчанию — 8000, как у `python -m api serve`.
const apiPort = process.env.API_PORT ?? '8000'
const apiTarget = `http://127.0.0.1:${apiPort}`

// Порт самого Vite — тоже из окружения, чтобы запуски не толкались на 5173.
const webPort = Number(process.env.WEB_PORT ?? 5173)

/**
 * Префикс пути, под которым живёт сайт: домена нет, адрес — IP машины плюс
 * случайная строка, чтобы сайт не нашли перебором.
 *
 * Задаётся снаружи, а не в файле: строка секретная, и в репозиторий ей нельзя.
 * В `pnpm dev`, `pnpm e2e` и обычной сборке переменной нет — значит `/`, то
 * есть ровно то, что было до префиксов.
 *
 * Приводится к виду `/что-то/`: Vite требует косую на обоих концах, а человек
 * в `.env` напишет как придётся.
 */
const basePath = normalizeBase(process.env.VITE_BASE_PATH)

function normalizeBase(raw: string | undefined): string {
  const trimmed = (raw ?? '').trim()
  if (!trimmed || trimmed === '/') return '/'
  return `/${trimmed.replace(/^\/+/, '').replace(/\/+$/, '')}/`
}

/**
 * Обфускация боевой сборки: код режется на части и обфусцируется.
 *
 * Только в `vite build` и только когда её не выключили: `pnpm dev`, `pnpm test`
 * и `pnpm e2e` идут без неё, иначе отладка превращается в гадание, а Playwright
 * — в лотерею. Выключатель для тех же целей — `KORITSU_OBFUSCATE=0`.
 *
 * Настройки умеренные намеренно. Взяты переименование имён и укрытие строк:
 * они мешают читать чужой код и почти ничего не стоят по времени и размеру. Не
 * взяты `debugProtection` и `selfDefending` — они ломают отладчик и падают в
 * автоматическом браузере (а его гонять на каждом прогоне проверок), и не взяты
 * `controlFlowFlattening` с `deadCodeInjection` — это кратный рост размера и
 * времени ради защиты, которую всё равно снимают за вечер.
 *
 * Обфускация — это задержка чужого чтения, а не запрет. Всё, что должно быть
 * тайной, живёт в службе, а не в браузере.
 */
const obfuscate = process.env.KORITSU_OBFUSCATE !== '0'

export default defineConfig(({ mode }) => ({
  base: basePath,
  plugins: [
    react(),
    // `apply: 'build'` у плагина ниже, но проверка по `mode` тут нужна тоже:
    // `vite build --mode development` — законный способ собрать читаемое.
    ...(mode === 'production' && obfuscate
      ? [
          obfuscator({
            // `global: true` — обфусцировать готовые куски сборки, а не каждый
            // исходный модуль по отдельности. Так под нож попадает и то, что
            // приехало из библиотек, и делается это десяток раз (по куску), а
            // не полторы тысячи (по модулю): на модулях та же работа занимала
            // бы минуты.
            global: true,
            options: {
              compact: true,
              // Имена — короткие бессмысленные. Это основная часть работы.
              identifierNamesGenerator: 'mangled',
              renameGlobals: false,
              // Строки уезжают в общий массив: искать по коду «Не удалось
              // войти» больше нельзя. Порог 0.75, а не 1: последняя четверть
              // строк стоит заметно дороже, чем прячет.
              stringArray: true,
              stringArrayThreshold: 0.75,
              stringArrayEncoding: ['base64'],
              splitStrings: false,
              // Заготовки Rollup для адресов кусков — не трогать.
              //
              // Плагин работает в `renderChunk`, а на этом шаге адреса
              // подгружаемых кусков в коде ещё не настоящие: вместо имени
              // файла стоит заготовка `!~{00f}~`, которую Rollup заменит
              // позже, отыскав её в готовом тексте. Уехав в массив строк и
              // закодировавшись в base64, заготовка перестаёт находиться —
              // Rollup оставляет её как есть, и в бою браузер просит
              // `assets/routes-!~{00f}~.js`, получает `index.html` и роняет
              // весь ленивый кусок: «Failed to fetch dynamically imported
              // module». То есть работает ровно то, что успело загрузиться до
              // первого `import()`, — страница входа, — а дальше пусто.
              //
              // Найдено на боевой сборке под префиксом: ни `pnpm dev`, ни
              // `pnpm e2e` этого не видят, потому что в них сборки нет вовсе.
              reservedStrings: ['!~\\{'],
              // Всё, что ломает отладку и Playwright, — выключено (см. выше).
              debugProtection: false,
              selfDefending: false,
              disableConsoleOutput: false,
              controlFlowFlattening: false,
              deadCodeInjection: false,
              // Карт исходников в бою нет, и обфускатору своей тоже не надо.
              sourceMap: false,
              target: 'browser',
            },
          }),
        ]
      : []),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Явный IPv4, а не `localhost`: в Node 17+ `localhost` разрешается сначала
    // в `::1`, и тогда `curl http://127.0.0.1:5171` и Playwright по тому же
    // адресу получают отказ соединения на работающем сервере.
    host: '127.0.0.1',
    port: webPort,
    strictPort: true,
    proxy: {
      // Cookie-сессия работает только на том же origin, поэтому весь `/api`
      // ходит через прокси Vite, а не по абсолютному адресу службы.
      // `ws: false` намеренно: потоки заданий — SSE, а не веб-сокеты.
      '/api': { target: apiTarget, changeOrigin: false },
      '/openapi.json': { target: apiTarget, changeOrigin: false },
      '/docs': { target: apiTarget, changeOrigin: false },
      '/health': { target: apiTarget, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    // Карты исходников — только не в бою: в боевой сборке они выключены.
    // Карта рядом с обфусцированным кодом означала бы обфускацию, снимаемую
    // одним кликом в браузере; плюс
    // это 5,7 МБ файлов, которые ни на что больше не годятся.
    sourcemap: mode !== 'production',
    rollupOptions: {
      output: {
        /**
         * Ручное деление на куски.
         *
         * Делим не «по красоте», а по тому, кто когда нужен:
         *
         *   react       каркас; нужен всем и всегда, меняется раз в полгода —
         *               значит держится в кэше браузера через выкаты;
         *   codemirror  редактор кода; нужен только на схемах и на правке
         *               нетекстовых тегов, а весит как треть всего остального;
         *   fonts       шрифты «Бумаги» подключаются CSS'ом, здесь их нет —
         *               про них см. `styles/`.
         *
         * Остальное Rollup режет сам по точкам `import()` (`app/areas.tsx`):
         * у каждой области сайта свой кусок, и первая страница тянет только
         * свой.
         */
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](@codemirror|@lezer|codemirror)[\\/]/.test(id)) {
            return 'codemirror'
          }
          if (/[\\/]node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/.test(id)) {
            return 'react'
          }
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Только модульные проверки рядом с кодом. Сквозные (`e2e/**/*.spec.ts`)
    // гоняет Playwright — своим запускателем, в настоящем браузере; Vitest
    // подобрал бы их по умолчанию и упал на первом же `@playwright/test`.
    include: ['src/**/*.test.{ts,tsx}'],
  },
}))
