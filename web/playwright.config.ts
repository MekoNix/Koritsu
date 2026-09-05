/**
 * Настройка сквозных проверок браузером.
 *
 * Проверяется склейка, которой нет ни у одного другого вида проверок: настоящий
 * браузер → дев-сервер Vite (он же прокси на службу, чтобы origin был один и
 * cookie сессии работала) → настоящая служба с очередью и воркером на временном
 * томе → поддельная модель по адресу. Подделан только тот, к кому уезжает ключ.
 *
 * **Стенд поднимается и гасится сам** — двумя записями `webServer`:
 *
 * 1. `e2e/stack-fg.sh` — служба, воркер и поддельная модель (`stack.sh` на
 *    переднем плане, чтобы Playwright мог их погасить);
 * 2. `pnpm dev` — сайт со своим `API_PORT`.
 *
 * `reuseExistingServer` включён: стенд, поднятый руками для разглядывания
 * глазами, повторно не поднимается и после прогона не гасится.
 *
 * **Один воркер и последовательные проверки.** Том и база у стенда общие, а
 * вошедший человек — состояние вкладки; два прогона разом делили бы одну
 * очередь и один журнал, из которого вылавливается токен подтверждения.
 *
 * Браузер один — Chromium из `~/.cache/ms-playwright` (сборка 1228, ей отвечает
 * `@playwright/test` 1.61). Окно 1440×900: макеты нарисованы на эту ширину, а
 * мобильная — ночь 2.
 */
import { defineConfig } from '@playwright/test'

import { API_PORT, BASE_URL, FAKE_PORT, STAND_DIR, WEB_PORT } from './e2e/tests/stand'

export default defineConfig({
  testDir: './e2e/tests',
  // Прогон целиком — путь человека от регистрации до выхода, и он длинный:
  // сборка DOCX зовёт LibreOffice, прогон модели идёт через очередь.
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],

  use: {
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 900 },
    // Трасса только на упавшей проверке: она весит мегабайты, а нужна ровно
    // тогда, когда по тексту ошибки непонятно, что случилось на экране.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
  },

  // Одна сборка, без `devices`: готовый набор «Desktop Chrome» подменяет и
  // окно (1280×720), и строку браузера — а нам нужна ширина макетов.
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
      command: 'pnpm dev',
      url: BASE_URL,
      reuseExistingServer: true,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: { API_PORT: String(API_PORT), WEB_PORT: String(WEB_PORT) },
    },
  ],
})
