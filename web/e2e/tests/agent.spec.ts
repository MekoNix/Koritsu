/**
 * Окно агента (Ctrl+J): задача → ходы по потоку → итог со ссылками на теги →
 * перегенерировать.
 *
 * Что здесь проверяется и чего не проверяет ни модульная проверка, ни `smoke.sh`.
 * Уровень 3 — единственный прогон, у которого значения приходят **вызовами
 * инструментов по ходу работы**, а не разбором одного ответа. На сайте это
 * четыре разных стыка: панель монтирована поверх любого экрана и берёт работу
 * из адреса; задание ставится из панели; ходы приезжают событиями `tag_closed`
 * в потоке задания; итог — список ключей, каждый ссылкой на свой тег. Ни один
 * из четырёх не виден ни в службе, ни в vitest.
 *
 * Ходы на стенде появляются по маркеру `[[FAKE:TOOLS]]` в задаче агента:
 * поддельная модель без принуждения инструменты не зовёт вовсе, и прогон
 * проходил бы вхолостую (`web/e2e/README.md`, «Ходы инструментами по
 * требованию»). Маркер уезжает в модель тем же путём, что и текст человека, —
 * то есть проверяется настоящий путь задачи от поля до промпта.
 */
import { expect, test } from '@playwright/test'

import { TAG_ONE, TAG_TWO, signUpAndLogin, t, templateDocx } from './helpers'

const ПРОЕКТ = 'Работа для агента'
const ЗАДАЧА = '[[FAKE:TOOLS]] Заполни оба тега отчёта своими словами.'

test('агент: Ctrl+J, задача с ходами, итог со ссылками, перегенерировать', async ({ page }) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'agent')

  // ── работа с шаблоном: агенту нужны теги, которые он поставит ──────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const создание = page.getByRole('dialog')
  await создание.getByLabel(t('projects.create.name')).fill(ПРОЕКТ)
  await создание.locator('input[type="file"]').setInputFiles(templateDocx())
  await создание.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // ── панель открывается горячей клавишей с любого экрана ───────────────────
  const панель = page.getByRole('dialog').filter({ hasText: t('agent.title') })
  await expect(панель).toHaveCount(0)
  await page.keyboard.press('Control+j')
  await expect(панель).toBeVisible()

  // Работа взята из адреса экрана под панелью, а не выбрана руками: выбора в
  // панели в этом случае быть не должно.
  await expect(панель.getByText(ПРОЕКТ)).toBeVisible()
  await expect(панель.getByLabel(t('agent.project.pick'))).toHaveCount(0)

  // ── задача и прогон ───────────────────────────────────────────────────────
  const поле = панель.getByLabel(t('agent.task.label'))
  await поле.fill(ЗАДАЧА)
  await панель.getByRole('button', { name: t('agent.run') }).click()

  // Ходы: событие `tag_closed` на каждый поставленный тег, ссылкой на тег.
  // `.first()`: тот же ключ повторяется ссылкой в итоге прогона, и оба раза
  // это одна и та же ссылка на один и тот же тег.
  const ход = (ключ: string) => панель.getByRole('link', { name: ключ, exact: true }).first()
  await expect(ход(TAG_ONE)).toBeVisible({ timeout: 120_000 })
  await expect(ход(TAG_TWO)).toBeVisible({ timeout: 120_000 })

  // Ответ модели одним куском в конце прогона (у петли потока наружу нет).
  await expect(панель.getByText(t('agent.text.title'))).toBeVisible({ timeout: 60_000 })

  // ── итог: что изменилось ──────────────────────────────────────────────────
  const итог = панель.getByText(t('agent.result.title'))
  await expect(итог).toBeVisible({ timeout: 60_000 })
  // Прогон дошёл до конца: строки «дошёл не до конца» на экране нет.
  await expect(панель.getByText(t('agent.result.notOk'))).toHaveCount(0)
  await expect(панель.getByText(t('agent.result.none'))).toHaveCount(0)
  // Ссылка ведёт на свой тег на экране отчёта — из панели можно уйти смотреть.
  await expect(ход(TAG_ONE).last()).toHaveAttribute(
    'href',
    new RegExp(`/reports/${projectId}\\?tag=`),
  )

  // ── перегенерировать: тот же прогон той же задачей ────────────────────────
  // Признак второго прогона — история прогонов работы: она приезжает из
  // очереди (`GET /api/jobs?project_id=…`), а не копится в браузере, и потому
  // говорит о службе, а не о состоянии компонента.
  const история = панель
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: t('agent.history.title') }) })
    .getByRole('listitem')
  await expect.poll(() => история.count(), { timeout: 60_000 }).toBe(1)

  const снова = панель.getByRole('button', { name: t('agent.regenerate') })
  await expect(снова).toBeVisible()
  await снова.click()
  await expect.poll(() => история.count(), { timeout: 120_000 }).toBe(2)
  await expect
    .poll(() => история.filter({ hasText: t('agent.status.done') }).count(), { timeout: 120_000 })
    .toBe(2)

  // ── панель закрывается тем же сочетанием и прогон не мешает экрану ────────
  await page.keyboard.press('Control+j')
  await expect(панель).toHaveCount(0)

  // Поставленное агентом видно на экране отчёта — значения настоящие.
  await page.goto(`/reports/${projectId}`)
  await expect(page.getByText(t('reports.tags.counter', { filled: 2, total: 2 }))).toBeVisible({
    timeout: 30_000,
  })
})
