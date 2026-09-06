/**
 * Экран отчёта: бланки работы, потолок истории значений, общая подсказка
 * прогона и прокрутка списка тегов.
 *
 * Четыре обещания, и каждое ломалось молча.
 *
 * 1. **Список тегов мотается.** На бланке в сорок тегов нижние были недоступны
 *    вовсе: колонка росла за край экрана, а прокручиваться было нечему.
 * 2. **Версий значения не больше пяти.** Шестая правка убирает первую, и это
 *    видно в истории тега — иначе каталог значений растёт без конца.
 * 3. **Общая подсказка прогона уезжает в задание.** Поле стоит у кнопки
 *    «сгенерировать всё», и написанное в нём обязано оказаться в `payload`
 *    задания, а не остаться на экране.
 * 4. **Бланк работы выбирается здесь.** Приложить и выбрать — разные действия:
 *    приложенный лежит про запас, а собирается работа по выбранному, и после
 *    выбора теги в колонке те, что в этом бланке.
 *
 * Модель зовётся один раз и на маленьком бланке: проверяется не её ответ, а то,
 * что уехало в задание.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { signUpAndLogin, t, templateDocx } from './helpers'
import { PYTHON, STAND_DIR } from './stand'

const РАБОТА = 'Отчёт с длинным бланком'

/** Первый тег длинного бланка — на нём проверяется история версий. */
const ТЕГ = 'цель'
/** Последний тег длинного бланка: до него нужно домотать. */
const ПОСЛЕДНИЙ = 'т40'

/**
 * Бланк на сорок с лишним тегов — тот случай, ради которого колонке нужна
 * прокрутка. Строится так же, как `templateDocx`: python-docx из общего venv,
 * файл в томе стенда.
 */
function longTemplateDocx(): string {
  const файл = path.join(STAND_DIR, 'бланк-длинный.docx')
  if (fs.existsSync(файл)) return файл
  execFileSync(
    PYTHON,
    [
      '-c',
      [
        'import sys',
        'from docx import Document',
        'документ = Document()',
        'документ.add_paragraph("Отчёт по практике")',
        `документ.add_paragraph("{{${ТЕГ}}}")`,
        'for н in range(1, 41):',
        '    документ.add_paragraph("{{т%02d}}" % н)',
        'документ.save(sys.argv[1])',
      ].join('\n'),
      файл,
    ],
    { stdio: 'pipe' },
  )
  return файл
}

test('отчёт: прокрутка тегов, пять версий, общая подсказка, выбор бланка', async ({ page }) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'reports')

  // ── работа с длинным бланком ──────────────────────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const создание = page.getByRole('dialog')
  await создание.getByLabel(t('projects.create.name')).fill(РАБОТА)
  await создание.locator('input[type="file"]').setInputFiles(longTemplateDocx())
  await создание.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // ── отчёт заводится из работы и привязывается к ней ───────────────────────
  // Кнопка уводит на сам заведённый отчёт: отчётов в работе несколько.
  await page.getByRole('button', { name: t('projects.runs.create.reports') }).click()
  await expect(page).toHaveURL(new RegExp(`/reports/${projectId}/[0-9a-f-]{36}$`))

  await page.goto(`/projects/${projectId}`)
  await expect(
    page.getByText(
      t('projects.runs.autoName', {
        unit: t('projects.runs.unit.reports'),
        n: 1,
        project: РАБОТА,
      }),
    ),
  ).toBeVisible({ timeout: 30_000 })

  await page.goto(`/reports/${projectId}`)
  const поле = page.getByRole('textbox', { name: t('reports.editor.field', { tag: ТЕГ }) })
  await expect(поле).toBeVisible({ timeout: 30_000 })

  // ── 1. список тегов мотается до последнего ────────────────────────────────
  // Тег в списке назван ключом без фигурных скобок: скобки нужны в бланке, где
  // подстановку надо отличить от текста, а в списке одних подстановок — нет.
  const последний = page.getByRole('button', { name: ПОСЛЕДНИЙ })
  await последний.scrollIntoViewIfNeeded()
  await expect(последний).toBeInViewport()

  // ── 2. шестая правка оставляет пять версий ────────────────────────────────
  const сохранить = page.getByRole('button', { name: t('common.action.save'), exact: true })
  for (let n = 1; n <= 6; n += 1) {
    await поле.fill(`Правка номер ${n}.`)
    await сохранить.click()
    await expect(page.getByText(t('reports.editor.byHand', { n }))).toBeVisible()
  }
  await page.getByRole('button', { name: t('reports.versions.title') }).click()
  await expect(page.getByText(t('reports.versions.count', { n: 5 }))).toBeVisible({
    timeout: 30_000,
  })
  await page.getByRole('button', { name: t('reports.versions.title') }).click()

  // ── 3. бланк работы: приложить и выбрать ──────────────────────────────────
  await page.getByRole('button', { name: t('reports.templates.action') }).click()
  const бланки = page.getByRole('dialog')
  await бланки.locator('input[type="file"]').setInputFiles(templateDocx())
  await бланки.getByRole('button', { name: t('reports.templates.attachFile') }).click()
  await expect(бланки.getByRole('button', { name: t('reports.templates.use') })).toBeVisible({
    timeout: 30_000,
  })
  await бланки.getByRole('button', { name: t('reports.templates.use') }).click()
  const подтверждение = page.getByRole('dialog').last()
  await подтверждение.getByRole('button', { name: t('reports.templates.use') }).click()
  await expect(page.getByText(t('reports.templates.active'))).toBeVisible({ timeout: 30_000 })
  await page.keyboard.press('Escape')

  // Теги теперь те, что в выбранном бланке: сорока тегов длинного больше нет.
  await expect(page.getByRole('button', { name: 'выводы' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: ПОСЛЕДНИЙ })).toHaveCount(0)
  // Значение пережило смену бланка: тег «цель» есть в обоих бланках.
  await expect(page.getByText(t('reports.editor.byHand', { n: 6 }))).toBeVisible()

  // ── 4. общая подсказка прогона уезжает в задание ──────────────────────────
  const ПОДСКАЗКА = 'писать в прошедшем времени'
  await page.getByRole('button', { name: t('reports.work.fillAll') }).click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('reports.fillAll.promptLabel')).fill(ПОДСКАЗКА)
  const задание = page.waitForRequest(
    (запрос) => запрос.url().includes('/api/jobs') && запрос.method() === 'POST',
  )
  await окно.getByRole('button', { name: t('reports.fillAll.start') }).click()
  const тело = JSON.parse((await задание).postData() ?? '{}') as {
    kind?: string
    payload?: { prompt?: string }
  }
  expect(тело.kind).toBe('fill_report')
  expect(тело.payload?.prompt).toBe(ПОДСКАЗКА)
})
