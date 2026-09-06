/**
 * Оболочка и запросы: сколько сайт спрашивает у службы и что у него в меню.
 *
 * Четыре проверки, и каждая ловит то, чего не поймать ни vitest'ом (там служба
 * подменена), ни `tests/api` (там нет браузера).
 *
 * 1. **Один запрос на загрузку.** Считаются настоящие запросы к `/api/` от
 *    первого кадра до первого экрана. Проверяется не «есть маршрут `bootstrap`»,
 *    а то, ради чего он заведён: отдельных `auth/me`, `modules`, `usage`,
 *    `workspaces`, `notifications` при загрузке больше не уходит. Считать
 *    запросы приходится браузером — только он знает, какие хуки проснулись.
 * 2. **Агента в сайдбаре нет.** Он не страница, а панель поверх экрана, и
 *    кнопка на него живёт в шапке. Пункт меню обещал бы место, куда можно уйти.
 *    Заодно проверяется, что название в сайдбаре ведёт на дашборд.
 * 3. **Разделы настроек названы по-новому.** «Конфигурация агентов» вместо двух
 *    разделов и «API Koritsu» вместо «ключей для скриптов»; старый адрес
 *    `/settings/keys` продолжает открываться — на разделы настроек дают ссылки.
 * 4. **Переставленная клетка переживает перезагрузку.** Порядок ленты живёт в
 *    браузере, и проверить это можно только браузером: включили режим правки,
 *    переставили, обновили страницу, порядок тот же.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'

/** Запросы к службе, кроме потока событий: поток — соединение, а не запрос. */
function считать(page: Page): string[] {
  const пути: string[] = []
  page.on('request', (запрос) => {
    const { pathname } = new URL(запрос.url())
    if (!pathname.startsWith('/api/') || pathname === '/api/events') return
    пути.push(pathname)
  })
  return пути
}

/** Порядок клеток ленты — именами из разметки, а не подписями на русском. */
async function порядок(ручки: Locator): Promise<string[]> {
  return ручки.evaluateAll((кнопки) => кнопки.map((к) => к.getAttribute('data-cell') ?? ''))
}

test.describe('оболочка', () => {
  test('первый экран собирается одним запросом сводки', async ({ page }) => {
    await signUpAndLogin(page, 'bootstrap')

    // Считаем с чистого листа: вход — свои запросы, а нас занимает загрузка
    // страницы уже вошедшего.
    const пути = считать(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    // Лента дорисовалась: клетка, которую кормит сводка, на месте.
    await expect(page.getByText(t('dashboard.usage.title'))).toBeVisible()

    expect(пути.filter((путь) => путь === '/api/bootstrap')).toHaveLength(1)

    // Ни одного отдельного запроса за тем, что уже приехало сводкой.
    const лишние = пути.filter(
      (путь) =>
        путь === '/api/auth/me' ||
        путь === '/api/modules' ||
        путь === '/api/usage' ||
        путь === '/api/notifications' ||
        путь.startsWith('/api/workspaces'),
    )
    expect(лишние, `лишние запросы: ${лишние.join(', ')}`).toEqual([])
  })

  test('в сайдбаре нет агента, а название ведёт на дашборд', async ({ page }) => {
    await signUpAndLogin(page, 'sidebar')
    await page.goto('/projects')

    const сайдбар = page.locator('aside').first()
    // Кнопка агента есть — но в шапке, а не в меню.
    await expect(
      page.getByRole('button', { name: new RegExp(t('shell.agent.label')) }),
    ).toBeVisible()
    await expect(сайдбар.getByRole('link', { name: t('shell.agent.label') })).toHaveCount(0)

    await сайдбар.getByRole('link', { name: t('shell.brand'), exact: true }).click()
    await expect(page).toHaveURL(/:\d+\/$/)
  })

  test('настройки: «Конфигурация агентов» и «API Koritsu»', async ({ page }) => {
    await signUpAndLogin(page, 'settings-names')
    await page.goto('/settings/profile')

    const разделы = page.getByRole('navigation', { name: t('settings.nav.label') })
    await expect(разделы.getByRole('link', { name: t('settings.nav.agent') })).toBeVisible()
    await expect(разделы.getByRole('link', { name: t('settings.nav.tokens') })).toBeVisible()

    // Ключи моделей теперь внутри «Конфигурации агентов», а не своим разделом.
    await разделы.getByRole('link', { name: t('settings.nav.agent') }).click()
    await expect(page.getByText(t('settings.agent.preset'))).toBeVisible()
    await expect(page.getByText(t('settings.keys.title'), { exact: true })).toBeVisible()

    // Старый адрес не упал в «страницу не найдена»: на разделы дают ссылки.
    await page.goto('/settings/keys')
    await expect(page).toHaveURL(/\/settings\/agent$/)
  })

  test('переставленная клетка ленты переживает перезагрузку', async ({ page }) => {
    await signUpAndLogin(page, 'dashboard-order')
    await page.goto('/')

    // Ручки живут в режиме правки: вне его лента показывает только клетки, и
    // случайное перетаскивание её не переставляет.
    await page.getByRole('button', { name: t('dashboard.edit.start') }).click()
    const ручки = page.locator('[data-cell]')
    await expect(ручки.first()).toBeVisible()
    const было = await порядок(ручки)
    expect(было.length).toBeGreaterThan(2)

    // Двигаем первую клетку вправо с клавиатуры: то же действие, что и мышью,
    // и оно же доказывает, что раскладка меняется не только указателем.
    await ручки.first().focus()
    await page.keyboard.press('ArrowRight')

    const стало = await порядок(ручки)
    expect(стало).not.toEqual(было)
    expect(стало[1]).toBe(было[0])

    await page.reload()
    await page.getByRole('button', { name: t('dashboard.edit.start') }).click()
    await expect(ручки.first()).toBeVisible()
    expect(await порядок(ручки)).toEqual(стало)
  })
})
