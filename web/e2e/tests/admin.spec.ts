/**
 * Админка: её видит только тот, у кого право есть.
 *
 * Право выдаётся тем же способом, каким его выдаёт владелец на боевой машине, —
 * строкой в базе (`UPDATE users SET is_admin=1`). Ручки «сделай меня админом» у
 * службы нет и заводить её нельзя: она и была бы дырой, ради закрытия которой
 * весь `/api/admin` закрыт `require_admin`.
 *
 * Проверяется ровно то, что нельзя проверить ни в службе, ни в vitest: сайт
 * узнаёт право из `is_admin` в `GET /api/auth/me`, показывает `/admin` и
 * по-прежнему не показывает ссылку на него ни в меню, ни на дашборде.
 */
import { execFileSync } from 'node:child_process'

import { expect, test } from '@playwright/test'

import { TAG_ONE, signUpAndLogin, t, templateDocx } from './helpers'
import { DB_FILE } from './stand'

/** Выдать право администратора прямо в базе тома. */
function сделатьАдмином(email: string): void {
  const python = process.env.PYTHON ?? '/home/kurisu/koritsu2/.venv/bin/python'
  execFileSync(
    python,
    [
      '-c',
      [
        'import sqlite3, sys',
        'связь = sqlite3.connect(sys.argv[1])',
        'курсор = связь.execute("UPDATE users SET is_admin=1 WHERE email=?", (sys.argv[2],))',
        'связь.commit()',
        'assert курсор.rowcount == 1, f"строк изменено: {курсор.rowcount}"',
      ].join('\n'),
      DB_FILE,
      email,
    ],
    { stdio: 'pipe' },
  )
}

test('право администратора открывает /admin и не появляется в меню', async ({ page }) => {
  const email = await signUpAndLogin(page, 'admin')

  // Пока права нет — честный отказ, а не пустой экран и не «не найдено».
  await page.goto('/admin')
  await expect(page.getByText(t('common.state.forbidden'))).toBeVisible()

  сделатьАдмином(email)

  // Перезагрузка перечитывает профиль: право приезжает полем `is_admin`.
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: t('admin.title') })).toBeVisible()
  await expect(page.getByRole('link', { name: t('admin.tab.queue') })).toBeVisible()

  // Вкладка — часть адреса, а не состояние страницы.
  await page.getByRole('link', { name: t('admin.tab.queue') }).click()
  await expect(page).toHaveURL(/\/admin\/queue$/)
  await expect(page.getByRole('heading', { name: t('admin.queue.title') })).toBeVisible()

  // Люди: свой человек в списке есть.
  await page.getByRole('link', { name: t('admin.tab.users') }).click()
  await expect(page.getByText(email)).toBeVisible()

  // И главное: ссылки на админку в оболочке нет ни у кого — попасть сюда можно
  // только прямым адресом (правка 2 макетов).
  await page.goto('/')
  await expect(page.locator('aside').getByRole('link', { name: t('shell.nav.admin') })).toHaveCount(
    0,
  )
  await expect(page.locator('a[href="/admin"]')).toHaveCount(0)
})

/**
 * Обзор админки: три графика с данными.
 *
 * Данные заводятся тем же путём, каким они появляются у владельца, — работой и
 * прогоном: регистрация даёт точку в ряду регистраций, прогон модели — расход
 * за сутки и строку в разбивке по видам. Подкладывать числа в базу здесь
 * нельзя: проверяется, что сайт показывает то, что служба посчитала, а не то,
 * что проверка ей подложила.
 */
test('обзор админки: расход, виды заданий и регистрации нарисованы с данными', async ({ page }) => {
  test.setTimeout(180_000)
  const email = await signUpAndLogin(page, 'overview')

  // ── работа и один прогон: иначе рисовать нечего ───────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const создание = page.getByRole('dialog')
  await создание.getByLabel(t('projects.create.name')).fill('Работа для обзора')
  await создание.locator('input[type="file"]').setInputFiles(templateDocx())
  await создание.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  await page.goto(`/reports/${projectId}`)
  const поле = page.getByRole('textbox', { name: t('reports.editor.field', { tag: TAG_ONE }) })
  await expect(поле).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: t('reports.editor.generate'), exact: true }).click()
  await expect(page.getByText(t('reports.tags.byAgent', { n: 1 }))).toBeVisible({ timeout: 90_000 })

  сделатьАдмином(email)

  // ── обзор ─────────────────────────────────────────────────────────────────
  await page.goto('/admin')
  // Голый `/admin` — это обзор: вкладка названа адресом, а не состоянием
  // страницы.
  await expect(page).toHaveURL(/\/admin\/overview$/)
  await expect(page.getByRole('heading', { name: t('admin.overview.usage') })).toBeVisible({
    timeout: 30_000,
  })
  // Данные есть — значит пустых состояний нет ни у сводки, ни у видов.
  await expect(page.getByText(t('admin.overview.empty'))).toHaveCount(0)
  await expect(page.getByText(t('admin.overview.noJobs'))).toHaveCount(0)

  // Три графика, каждый — картинка со своим именем: это единственное, чем один
  // рисованный svg отличается от соседнего для того, кто смотрит не глазами.
  for (const ключ of ['usage', 'kinds', 'registrations']) {
    await expect(page.getByRole('img', { name: t(`admin.overview.${ключ}`) })).toBeVisible()
  }

  /** Таблица графика для скринридера: те же числа, только текстом. */
  const таблица = (подпись: string) =>
    page.locator('table').filter({ has: page.locator('caption', { hasText: подпись }) })

  // Ряд расхода — по строке на каждый день периода (умолчание — 30), и хотя бы
  // в одном дне число не нулевое: прогон только что был.
  const расход = таблица(t('admin.overview.usage'))
  await expect(расход.locator('tbody tr')).toHaveCount(30)
  const списано = await расход.locator('tbody tr td:nth-child(2)').allInnerTexts()
  expect(списано.some((число) => /[1-9]/.test(число))).toBe(true)

  // Разбивка по видам: прогон, который мы только что заказали, в ней есть.
  const виды = таблица(t('admin.overview.kinds'))
  await expect(виды.locator('tbody tr').filter({ hasText: 'fill_tag' })).toHaveCount(1)

  // Регистрации: свой человек заведён сегодня, значит день не пустой.
  const регистрации = таблица(t('admin.overview.registrations'))
  const заведено = await регистрации.locator('tbody tr td:nth-child(2)').allInnerTexts()
  expect(заведено.some((число) => /[1-9]/.test(число))).toBe(true)

  // Период — переключателем, и ряд перерисовывается под него.
  await page
    .getByRole('radiogroup', { name: t('admin.overview.period') })
    .getByRole('radio', { name: t('admin.overview.days', { n: 7 }) })
    .click()
  await expect(таблица(t('admin.overview.usage')).locator('tbody tr')).toHaveCount(7)
})
