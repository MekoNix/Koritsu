/**
 * Отчётов в работе несколько: свой бланк, свои значения, своя первая страница.
 *
 * Пять обещаний, и каждое ломается молча.
 *
 * 1. **Два отчёта в одной работе не мешают друг другу.** У каждого свой бланк,
 *    значит свои теги, и своё значение под общим ключом. До этого набор
 *    значений у работы был один, и второй отчёт затирал первый.
 * 2. **Первая страница остаётся на карточке.** Сборка кладёт её картинкой, а не
 *    рисует на лету, — значит она переживает перезагрузку страницы.
 * 3. **Удаление сносит один отчёт.** Значения соседа остаются на месте.
 * 4. **Непонятные конструкции бланка свёрнуты.** Одна строка со счётом, список
 *    — под раскрытием: конструкций бывает десяток, а колонка тегов одна.
 * 5. **Тег назван описанием, а не ключом.** Сверху то, что после двоеточия в
 *    `{{ключ:описание}}`, снизу ключ без фигурных скобок.
 *
 * Модель здесь не зовётся вовсе: проверяется раскладка документов по отчётам, а
 * не ответ модели. Сборка зовётся один раз и на маленьком бланке — она нужна
 * ради картинки первой страницы.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'
import { PYTHON, STAND_DIR } from './stand'

const РАБОТА = 'Курсовая с двумя отчётами'

/** Первый бланк: тег с описанием и конструкция, которой сборщик не понимает. */
const ТЕГ_ОДИН = 'цель'
const ОПИСАНИЕ_ОДИН = 'Цель работы'
const КОНСТРУКЦИЯ = '{% for строка in таблица %}'

/** Второй бланк: другой тег, чтобы разницу было видно по колонке тегов. */
const ТЕГ_ДВА = 'аннотация'

const ЗНАЧЕНИЕ_ОДИН = 'Значение первого отчёта.'
const ЗНАЧЕНИЕ_ДВА = 'Значение второго отчёта.'

/**
 * Бланк DOCX из готовых абзацев — тем же способом, что и остальные проверки:
 * `python-docx` из общего venv, файл в томе стенда.
 */
function бланк(имя: string, абзацы: string[]): string {
  const файл = path.join(STAND_DIR, `${имя}.docx`)
  if (fs.existsSync(файл)) return файл
  execFileSync(
    PYTHON,
    [
      '-c',
      [
        'import sys',
        'from docx import Document',
        'документ = Document()',
        ...абзацы.map((текст) => `документ.add_paragraph(${JSON.stringify(текст)})`),
        'документ.save(sys.argv[1])',
      ].join('\n'),
      файл,
    ],
    { stdio: 'pipe' },
  )
  return файл
}

test('отчёты работы: два бланка, превью, удаление и имена тегов', async ({ page }) => {
  test.setTimeout(300_000)
  await signUpAndLogin(page, 'reportlist')

  // ── работа с первым бланком ───────────────────────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const создание = page.getByRole('dialog')
  await создание.getByLabel(t('projects.create.name')).fill(РАБОТА)
  await создание
    .locator('input[type="file"]')
    .setInputFiles(
      бланк('бланк-первый', ['Отчёт', `{{${ТЕГ_ОДИН}:${ОПИСАНИЕ_ОДИН}}}`, КОНСТРУКЦИЯ]),
    )
  await создание.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // ── список отчётов работы: пока пусто ─────────────────────────────────────
  await page.goto(`/reports?project=${projectId}`)
  await expect(page.getByText(t('reports.list.emptyTitle'))).toBeVisible({ timeout: 30_000 })

  // ── первый отчёт: собственный документ работы, её же бланк ────────────────
  await page
    .getByRole('button', { name: t('reports.list.create') })
    .first()
    .click()
  let окно = page.getByRole('dialog')
  await окно.getByLabel(t('reports.list.nameLabel')).fill('Глава 1')
  await окно.getByRole('button', { name: t('reports.list.createAction') }).click()
  await expect(page).toHaveURL(new RegExp(`/reports/${projectId}/[0-9a-f-]{36}`), {
    timeout: 30_000,
  })

  // 5. Тег назван описанием, ключ стоит под ним и без фигурных скобок.
  const строка_тега = page.getByRole('button', { name: ОПИСАНИЕ_ОДИН })
  await expect(строка_тега).toBeVisible({ timeout: 30_000 })
  await expect(строка_тега).toContainText(ТЕГ_ОДИН)
  await expect(строка_тега).not.toContainText('{{')

  // 4. Конструкция названа числом, а список свёрнут.
  const конструкции = page
    .locator('details')
    .filter({ hasText: t('reports.tags.unknownConstructs', { n: 1 }) })
  await expect(конструкции).toBeVisible()
  await expect(конструкции.getByText(КОНСТРУКЦИЯ)).toBeHidden()
  await конструкции.locator('summary').click()
  await expect(конструкции.getByText(КОНСТРУКЦИЯ)).toBeVisible()

  // Значение первого отчёта.
  const поле_один = page.getByRole('textbox', {
    name: t('reports.editor.field', { tag: ТЕГ_ОДИН }),
  })
  await поле_один.fill(ЗНАЧЕНИЕ_ОДИН)
  await page.getByRole('button', { name: t('common.action.save'), exact: true }).click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 1 }))).toBeVisible({
    timeout: 30_000,
  })

  // ── второй отчёт: другой бланк, приложенный прямо в окне ──────────────────
  await page.goto(`/reports?project=${projectId}`)
  await page
    .getByRole('button', { name: t('reports.list.create') })
    .first()
    .click()
  окно = page.getByRole('dialog')
  await окно.getByLabel(t('reports.list.nameLabel')).fill('Приложение')
  await окно
    .locator('input[type="file"]')
    .setInputFiles(бланк('бланк-второй', ['Приложение', `{{${ТЕГ_ДВА}}}`]))
  await окно.getByRole('button', { name: t('reports.templates.attachFile') }).click()
  // Бланк должен доехать до службы раньше, чем заводится отчёт: иначе отчёт
  // получит пустой выбор бланка. Приложенный файл уходит из окна — это и ждём.
  await expect(окно.getByRole('button', { name: t('reports.templates.attachFile') })).toHaveCount(
    0,
    { timeout: 30_000 },
  )
  await окно.getByRole('button', { name: t('reports.list.createAction') }).click()
  await expect(page).toHaveURL(new RegExp(`/reports/${projectId}/[0-9a-f-]{36}`), {
    timeout: 30_000,
  })

  // 1. Теги у второго отчёта свои, и значения первого сюда не приехали.
  const поле_два = page.getByRole('textbox', { name: t('reports.editor.field', { tag: ТЕГ_ДВА }) })
  await expect(поле_два).toBeVisible({ timeout: 30_000 })
  await expect(поле_два).toHaveValue('')
  await expect(page.getByRole('button', { name: ОПИСАНИЕ_ОДИН })).toHaveCount(0)
  await поле_два.fill(ЗНАЧЕНИЕ_ДВА)
  await page.getByRole('button', { name: t('common.action.save'), exact: true }).click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 1 }))).toBeVisible({
    timeout: 30_000,
  })

  // ── 2. сборка кладёт первую страницу картинкой ────────────────────────────
  // Кнопка сборки стоит и в шапке колонки превью, и в её пустом состоянии:
  // пока превью не собрано, их две, и нужна любая.
  await page
    .getByRole('button', { name: t('reports.pdf.build'), exact: true })
    .first()
    .click()
  await expect(page.getByRole('link', { name: t('reports.pdf.downloadPdf') })).toBeVisible({
    timeout: 180_000,
  })

  await page.goto(`/reports?project=${projectId}`)
  const карточки = page.getByTestId('report-cards')
  const карточка_два = карточки.getByRole('listitem').filter({ hasText: 'Приложение' })
  await expect(карточка_два.locator('img')).toBeVisible({ timeout: 60_000 })
  // Картинка хранится, а не рисуется на лету: перезагрузка её не теряет.
  await page.reload()
  await expect(карточка_два.locator('img')).toBeVisible({ timeout: 60_000 })

  // ── 3. удаление сносит один отчёт, сосед остаётся целым ───────────────────
  await карточка_два
    .getByRole('button', { name: t('reports.list.deleteAction', { name: 'Приложение' }) })
    .click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: t('reports.list.delete'), exact: true })
    .click()
  await expect(карточка_два).toHaveCount(0, { timeout: 30_000 })

  const карточка_один = карточки.getByRole('listitem').filter({ hasText: 'Глава 1' })
  await expect(карточка_один).toHaveCount(1)
  await карточка_один.getByRole('link').first().click()
  await expect(
    page.getByRole('textbox', { name: t('reports.editor.field', { tag: ТЕГ_ОДИН }) }),
  ).toHaveValue(ЗНАЧЕНИЕ_ОДИН, { timeout: 30_000 })
})
