/**
 * Нетекстовый тег: правка значения JSON'ом, проверка формы, отказ службы.
 *
 * Отдельной проверкой, потому что редактор здесь другой — не `<textarea>`, а
 * CodeMirror, — и ломается он ровно там, где модульная проверка ничего не
 * видит: ввод идёт в `contenteditable`, значение приходит в React событием
 * редактора, а кнопка «сохранить» гаснет по разбору того, что набрано. Правило
 * же формы (`values.validateValue`) проверено отдельно и здесь не пересчитывается
 * — здесь проверяется, что оно доехало до экрана.
 *
 * Шаблон свой: у общего (`helpers.templateDocx`) оба тега текстовые, а тип тега
 * служба угадывает по метке (`hokoku.manifest.suggest_type`), поэтому тег назван
 * «таблица» — так он и приезжает с типом `table`.
 *
 * Модель не зовётся ни разу: проверяется рука человека, а не прогон.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'
import { PYTHON, STAND_DIR } from './stand'

const ПРОЕКТ = 'Таблица тегом'
const ТЕГ = 'таблица'

/** Шаблон с одним тегом, у которого тип по метке — `table`. */
function шаблонСТаблицей(): string {
  const файл = path.join(STAND_DIR, 'шаблон-таблица.docx')
  if (fs.existsSync(файл)) return файл
  execFileSync(
    PYTHON,
    [
      '-c',
      [
        'import sys',
        'from docx import Document',
        'документ = Document()',
        'документ.add_paragraph("Отчёт с таблицей")',
        `документ.add_paragraph("{{${ТЕГ}}}")`,
        'документ.save(sys.argv[1])',
      ].join('\n'),
      файл,
    ],
    { stdio: 'inherit' },
  )
  return файл
}

test('нетекстовый тег правится JSON’ом, кривая форма не сохраняется', async ({ page }) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'jsonvalue')

  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const создание = page.getByRole('dialog')
  await создание.getByLabel(t('projects.create.name')).fill(ПРОЕКТ)
  await создание.locator('input[type="file"]').setInputFiles(шаблонСТаблицей())
  await создание.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  await page.goto(`/reports/${projectId}`)

  // Поле — редактор JSON, а не текстовое: тип тега `table`.
  const редактор = page.getByRole('textbox', {
    name: t('reports.editor.jsonField', { tag: ТЕГ }),
  })
  await expect(редактор).toBeVisible({ timeout: 30_000 })

  // В пустом теге стоит заготовка по типу, а не пустые скобки: без неё человек
  // не знает ни имён полей, ни того, что строки — это список списков.
  await expect(редактор).toContainText('"rows"')

  const сохранить = page.getByRole('button', { name: t('common.action.save'), exact: true })

  async function набрать(текст: string) {
    await редактор.click()
    await page.keyboard.press('ControlOrMeta+a')
    await page.keyboard.press('Delete')
    // `insertText`, а не посимвольный ввод: CodeMirror сам закрывает скобки и
    // кавычки, и набранный по буквам JSON превратился бы в мусор.
    await page.keyboard.insertText(текст)
  }

  // ── кривая форма: беда названа полем, сохранить нельзя ────────────────────
  await набрать('{"type":"table","rows":[["a"],["b","c"]]}')
  await expect(page.getByText(t('reports.json.error.raggedRows'))).toBeVisible()
  await expect(сохранить).toBeDisabled()

  // ── вовсе не JSON: своя беда, а не «форма не та» ──────────────────────────
  await набрать('{ rows: }')
  await expect(page.getByText(t('reports.json.error.badJson'))).toBeVisible()
  await expect(сохранить).toBeDisabled()

  // ── годная таблица сохраняется и становится версией ───────────────────────
  await набрать('{"type":"table","rows":[["Опыт","Время"],["1","12"]],"header":true}')
  await expect(page.getByText(t('reports.json.error.badJson'))).toHaveCount(0)
  await сохранить.click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 1 }))).toBeVisible({
    timeout: 30_000,
  })

  // Перечитанное значение приезжает тем же JSON'ом — значит уехало оно целиком,
  // а не текстом в поле `text`.
  await page.reload()
  await expect(редактор).toContainText('"Опыт"', { timeout: 30_000 })
})
