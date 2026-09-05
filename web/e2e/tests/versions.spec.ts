/**
 * Версии тега со сравнением и возвратом, экспорт работы и ссылка на файл в
 * колокольчике.
 *
 * Две вещи в одном пути, и они действительно один путь: человек правит
 * значение, сравнивает с прежним, возвращает прежнее — и скачивает готовое.
 *
 * Модель здесь не зовётся ни разу, и это не экономия, а точность: сравнение
 * версий проверяется на текстах, которые проверка написала сама и знает
 * дословно, а ответ подделки на два прогона одинаков — сравнивать было бы
 * нечего. Прогон модели проверяется в `flow.spec.ts` и `agent.spec.ts`.
 */
import { expect, test } from '@playwright/test'

import { TAG_ONE, signUpAndLogin, t, templateDocx } from './helpers'

const ПРОЕКТ = 'Версии и выгрузка'
const ПЕРВОЕ = 'Цель работы — разобрать сортировку пузырьком.'
const ВТОРОЕ = 'Цель работы — разобрать сортировку слиянием.'

test('версии: сравнение по словам и возврат; экспорт: файл в колокольчике', async ({ page }) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'versions')

  // ── работа с шаблоном ─────────────────────────────────────────────────────
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

  // ── две версии тега, написанные рукой ─────────────────────────────────────
  await page.goto(`/reports/${projectId}`)
  const поле = page.getByRole('textbox', { name: t('reports.editor.field', { tag: TAG_ONE }) })
  await expect(поле).toBeVisible({ timeout: 30_000 })

  const сохранить = page.getByRole('button', { name: t('common.action.save'), exact: true })
  await поле.fill(ПЕРВОЕ)
  await сохранить.click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 1 }))).toBeVisible()
  await поле.fill(ВТОРОЕ)
  await сохранить.click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 2 }))).toBeVisible()

  // ── история: сравнение первой версии с текущей ────────────────────────────
  await page.getByRole('button', { name: t('reports.versions.title') }).click()
  await page.getByRole('checkbox', { name: t('reports.versions.compareWith', { n: 1 }) }).check()
  await expect(
    page.getByRole('heading', { name: t('reports.versions.compareOf', { a: 1, b: 2 }) }),
  ).toBeVisible({ timeout: 30_000 })

  // Сравнение по словам, а не по строкам: изменилось одно слово, и в разметке
  // должно быть ровно оно — убранное `<del>` и добавленное `<ins>`.
  const убрано = page.locator('del')
  const добавлено = page.locator('ins')
  await expect(убрано.filter({ hasText: 'пузырьком' })).toBeVisible()
  await expect(добавлено.filter({ hasText: 'слиянием' })).toBeVisible()
  // Неизменившееся в разметку правки не попало: иначе это не diff, а два текста.
  await expect(убрано.filter({ hasText: 'Цель' })).toHaveCount(0)

  // ── возврат первой версии ─────────────────────────────────────────────────
  await page
    .getByRole('listitem')
    .filter({ hasText: 'v1' })
    .getByRole('button', { name: t('reports.versions.rollback') })
    .click()
  const подтверждение = page.getByRole('dialog', {
    name: t('reports.versions.rollbackTitle', { n: 1 }),
  })
  await expect(подтверждение).toBeVisible()
  await подтверждение.getByRole('button', { name: t('reports.versions.rollback') }).click()

  // Возврат — это новая версия с прежним текстом, а не удаление второй.
  await expect(поле).toHaveValue(ПЕРВОЕ)
  await expect(page.getByText(t('reports.editor.byHand', { n: 3 }))).toBeVisible()

  // ── экспорт: задание, готовые файлы, ссылка в колокольчике ────────────────
  await page.goto(`/projects/${projectId}`)
  await page.getByRole('button', { name: t('projects.export.action') }).click()
  const выгрузка = page.getByRole('dialog', { name: t('projects.export.title') })
  await expect(выгрузка).toBeVisible()

  // Пунктов два, по заданию на пункт: «Документ (Word и
  // PDF)» — прогон `build`, «Архив» — `export`. Проверяем, что их именно два:
  // третий пункт означал бы, что вернулся выбор без разницы — Word и PDF
  // отдельными строками за один и тот же прогон.
  await expect(выгрузка.getByRole('radio')).toHaveCount(2)
  await expect(
    выгрузка.getByRole('radio', { name: t('projects.export.format.document') }),
  ).toBeVisible()
  // Здесь берётся архив: он собирается без LibreOffice и не зависит от того,
  // что стоит на машине.
  await выгрузка.getByRole('radio', { name: t('projects.export.format.archive') }).check()
  await выгрузка.getByRole('button', { name: t('projects.export.start') }).click()
  await expect(выгрузка.getByText(t('projects.export.ready'))).toBeVisible({ timeout: 120_000 })

  const файл = выгрузка.getByRole('link', { name: t('projects.export.file.file') })
  await expect(файл).toHaveAttribute('href', /\/api\/projects\/.+\/artifacts\/.+/)
  await выгрузка.getByRole('button', { name: t('ui.dialog.close') }).click()

  // ── колокольчик: то же уведомление и та же ссылка ─────────────────────────
  await page.getByRole('button', { name: t('shell.notifications.label') }).click()
  const список = page.getByRole('menu')
  await expect(список.getByRole('menuitem').first()).toContainText(t('notifications.jobDone'), {
    timeout: 30_000,
  })
  // Вид задания назван по-русски, а не словом службы (`export`).
  await expect(список.getByText(t('notifications.kind.export'))).toBeVisible()

  const скачать = список.getByRole('link', { name: t('notifications.download') }).first()
  await expect(скачать).toHaveAttribute('href', /\/api\/projects\/.+\/artifacts\/.+/)

  // Скачивание настоящее: файл приезжает браузером, а не проверяется по ссылке.
  const [загрузка] = await Promise.all([page.waitForEvent('download'), скачать.click()])
  expect(await загрузка.failure()).toBeNull()
  expect(загрузка.suggestedFilename()).toMatch(/\.zip$/)
})
