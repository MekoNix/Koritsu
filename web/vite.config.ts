import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Порт службы: у каждого агента ночного прогона он свой (A — 8001, B — 8002, …),
// поэтому берётся из окружения, а по умолчанию — 8000, как у `python -m api serve`.
const apiPort = process.env.API_PORT ?? '8000'
const apiTarget = `http://127.0.0.1:${apiPort}`

// Порт самого Vite — тоже из окружения, чтобы агенты не толкались на 5173.
const webPort = Number(process.env.WEB_PORT ?? 5173)

export default defineConfig({
  plugins: [react()],
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
    sourcemap: true,
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
})
