/**
 * Настройка проверки боевой сборки: браузер ходит не по дев-серверу, а по
 * собранному `dist`.
 *
 * Зачем отдельно от `playwright.config.ts`. Обычные сквозные проверки поднимают
 * `pnpm dev`: там нет ни деления на куски, ни ленивых `import()` по областям,
 * ни обфускации, ни префикса пути. Именно эта четвёрка и ломается — куском,
 * который в бою просят не по тому адресу и который браузер молча не загружает.
 * Поймать это может только настоящая сборка, поднятая как в бою.
 *
 * **Сборку надо собрать заранее** — этот конфиг её не собирает намеренно:
 * префикс пути задаётся на сборке (`VITE_BASE_PATH`), и пересобирать чужой
 * `dist` под свои умолчания значило бы проверять не то, что выкатывают.
 *
 *     cd web
 *     VITE_BASE_PATH=<префикс> pnpm build
 *     pnpm e2e:dist
 *
 * Префикс не задаётся здесь второй раз, а вычитывается из самого `dist`
 * (`index.html`, адрес первого куска): разъехавшийся префикс дал бы показ, на
 * котором ничего не грузится, и разбирались бы с ним, а не с сайтом.
 *
 * Стенд службы — тот же самый (`e2e/stack-fg.sh`), и порты те же: проверка
 * ходит по настоящей службе с поддельной моделью.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from '@playwright/test'

import { API_PORT, FAKE_PORT, STAND_DIR } from './e2e/tests/stand'

// Каталог этого файла: `__dirname` здесь не годится — файл грузится как модуль
// ES (`"type": "module"` в `package.json`), а там его нет.
const DIST = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'dist')

/**
 * Префикс пути собранного сайта: `/k7f3x9/` или `/`.
 *
 * Берётся из `dist/index.html` — из адреса первого куска, который туда вписал
 * Rollup. Другого честного источника нет: `VITE_BASE_PATH` на сборке мог быть
 * какой угодно, а переспрашивать его у человека значит спрашивать то, что уже
 * записано в файле.
 */
function префиксСборки(): string {
  const индекс = path.join(DIST, 'index.html')
  if (!fs.existsSync(индекс)) {
    throw new Error(
      `нет собранного сайта: ${индекс}. Собрать — «VITE_BASE_PATH=<префикс> pnpm build»`,
    )
  }
  const html = fs.readFileSync(индекс, 'utf8')
  const найдено = /<script[^>]+src="([^"]*)\/assets\//.exec(html)
  if (!найдено) throw new Error(`в ${индекс} не нашёлся адрес куска — сборка не та?`)
  const префикс = найдено[1] as string
  return префикс === '' ? '/' : `${префикс}/`
}

export const BASE_PATH = префиксСборки()

const PREVIEW_PORT = Number(process.env.PREVIEW_PORT ?? 4173)

/**
 * Адрес показа вместе с префиксом. Относительные переходы в проверке (`goto('/')`)
 * считаются от него, то есть попадают под префикс — как и у человека в бою.
 */
export const DIST_URL = `http://127.0.0.1:${PREVIEW_PORT}${BASE_PATH}`

export default defineConfig({
  testDir: './e2e/tests',
  testMatch: /dist\.spec\.ts$/,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  // Свой каталог: иначе трассы этой проверки легли бы поверх трасс обычной.
  outputDir: './test-results-dist',

  use: {
    baseURL: DIST_URL,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
  },

  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],

  webServer: [
    {
      command: `bash e2e/stack-fg.sh ${STAND_DIR}`,
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: true,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: { API_PORT: String(API_PORT), FAKE_PORT: String(FAKE_PORT) },
    },
    {
      // `vite preview` отдаёт `dist` под тем же префиксом, под которым он
      // собран, и проксирует `/api` на службу — ровно то, что в бою делает
      // Caddy с одного имени.
      command: 'pnpm preview',
      url: DIST_URL,
      reuseExistingServer: true,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        API_PORT: String(API_PORT),
        PREVIEW_PORT: String(PREVIEW_PORT),
        VITE_BASE_PATH: BASE_PATH,
      },
    },
  ],
})
