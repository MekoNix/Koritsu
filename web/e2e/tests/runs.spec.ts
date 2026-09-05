/**
 * Журнал запусков работы браузером: пусто, заведение отчёта и решения из
 * работы, порядок списка и удаление записи.
 *
 * Проверяется то, ради чего журнал заведён: карточка работы отвечает на вопрос
 * «что здесь уже сделано», а не только «куда можно пойти». Отсюда четыре шага:
 *
 * 1. у новой работы журнал пуст, и это не ошибка;
 * 2. «Создать отчёт» ставит запись и уводит на экран отчёта — отчёт заводится
 *    отдельно и привязывается к текущей работе; то же с решением;
 * 3. порядок списка считает служба, и он меняется выбором в списке порядка;
 * 4. запись убирается из журнала — тем же действием, каким из работы удаляется
 *    схема (у схемы такая же строка журнала, её заводит модуль схем).
 *
 * Имена в журнале собирает сайт («Отчёт 1 — <работа>»): служба хранит номер и
 * то имя, которое человек дал сам, а по-русски называет запуск интерфейс.
 *
 * Правила устойчивости — те же, что у остальных сценариев: тексты ключами
 * перевода, ожидание через `expect`, поиск по ролям и подписям.
 */
import { expect, test } from '@playwright/test'

import { signUpAndLogin, t, templateDocx } from './helpers'

const РАБОТА = 'Журнал запусков'

/** Имя, которое сайт рисует запуску без своего имени. */
function имяЗапуска(module: string, n: number): string {
  return t('projects.runs.autoName', {
    unit: t(`projects.runs.unit.${module}`),
    n,
    project: РАБОТА,
  })
}

test('журнал запусков: пусто, отчёт и решение из работы, порядок, удаление', async ({ page }) => {
  await signUpAndLogin(page, 'runs')

  // ── работа с шаблоном ─────────────────────────────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('projects.create.name')).fill(РАБОТА)
  await окно.locator('input[type="file"]').setInputFiles(templateDocx())
  await окно.getByRole('button', { name: t('common.action.create') }).click()

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // ── 1. новая работа: журнал пуст ──────────────────────────────────────────
  await expect(page.getByText(t('projects.runs.empty'))).toBeVisible()

  // ── 2. отчёт из работы: запись и переход в модуль ─────────────────────────
  await page.getByRole('button', { name: t('projects.runs.create.reports') }).click()
  await expect(page).toHaveURL(new RegExp(`/reports/${projectId}$`))

  await page.goto(`/projects/${projectId}`)
  const отчёт = имяЗапуска('reports', 1)
  await expect(page.getByText(отчёт)).toBeVisible()

  // ── 2а. решение из работы: вторая запись, второй модуль ───────────────────
  await page.getByRole('button', { name: t('projects.runs.create.kadai') }).click()
  await expect(page).toHaveURL(new RegExp(`/kadai/${projectId}$`))

  await page.goto(`/projects/${projectId}`)
  const решение = имяЗапуска('kadai', 1)
  await expect(page.getByText(решение)).toBeVisible()

  // ── 3. порядок считает служба ─────────────────────────────────────────────
  // Строки журнала узнаются по имени работы: имя запуска сайт собирает из
  // модуля, номера и её названия, и больше нигде на странице оно не стоит.
  const строки = page.getByRole('listitem').filter({ hasText: РАБОТА })
  await expect(строки).toHaveCount(2)
  // Новые сверху — умолчание: решение завели последним.
  await expect(строки.first()).toContainText(решение)

  await page.getByLabel(t('projects.runs.sort.label')).selectOption('old')
  await expect(строки.first()).toContainText(отчёт)

  // ── 4. удаление записи ────────────────────────────────────────────────────
  await page.getByRole('button', { name: t('projects.runs.remove', { name: решение }) }).click()
  await expect(page.getByText(решение)).toHaveCount(0)
  await expect(page.getByText(отчёт)).toBeVisible()
})
