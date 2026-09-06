/**
 * Главная отчётов: свои отчёты сразу, работа — отбор, а не шаг.
 *
 * Восемь обещаний, и каждое ломается молча.
 *
 * 1. **Отчёты видны сразу.** `/reports` показывает отчёты всех работ
 *    пространства одним списком: шага «сначала выберите работу» перед ними нет.
 * 2. **Отчёт заводится с этой же страницы**, окном с выбором работы: работа
 *    называется в окне, бланк прикладывается там же и сразу становится
 *    выбранным.
 * 3. **Два отчёта разных работ не мешают друг другу.** У каждого свой бланк,
 *    значит свои теги, и своё значение — до этого набор значений у работы был
 *    один.
 * 4. **Работа — отбор над сеткой.** Выбранная работа встаёт в адрес
 *    (`?project=`), по которому приходят и старые ссылки; поиск сужает список
 *    и по имени отчёта, и по имени работы.
 * 5. **Первая страница остаётся на карточке.** Сборка кладёт её картинкой, а не
 *    рисует на лету, — значит она переживает перезагрузку страницы.
 * 6. **Удаление сносит один отчёт.** Сосед из другой работы остаётся на месте.
 * 7. **Первый отчёт наследует написанное в работе.** Работа живёт до всяких
 *    отчётов: в ней уже заполняли теги. Кнопка «Создать отчёт» обязана открыть
 *    тот же документ, а не пустой, — иначе написанное пропадает с экрана.
 * 8. **Отчёт переименовывается прямо на карточке**, и новое имя видно и в
 *    заголовке его экрана, и в журнале работы: имя одно на все три места.
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

/** Две работы: отчёты обеих обязаны стоять в одном списке. */
const КУРСОВАЯ = 'Курсовая по алгоритмам'
const ПРАКТИКА = 'Отчёт по практике'

/** Первый бланк: тег с описанием и конструкция, которой сборщик не понимает. */
const ТЕГ_ОДИН = 'цель'
const ОПИСАНИЕ_ОДИН = 'Цель работы'
const КОНСТРУКЦИЯ = '{% for строка in таблица %}'

/** Второй бланк: другой тег, чтобы разницу было видно по колонке тегов. */
const ТЕГ_ДВА = 'аннотация'

const ЗНАЧЕНИЕ_ОДИН = 'Значение первого отчёта.'
const ЗНАЧЕНИЕ_ДВА = 'Значение второго отчёта.'

/** Имена отчётов: данные при создании и данное переименованием. */
const ИМЯ_ОДИН = 'Глава 1'
const ИМЯ_ОДИН_НОВОЕ = 'Введение'
const ИМЯ_ДВА = 'Дневник'

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

/** Завести работу: с бланком или без него. → её идентификатор. */
async function завести(
  page: import('@playwright/test').Page,
  имя: string,
  файл?: string,
): Promise<string> {
  await page.goto('/projects')
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('projects.create.name')).fill(имя)
  if (файл) await окно.locator('input[type="file"]').setInputFiles(файл)
  await окно.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  return (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string
}

test('главная отчётов: отчёты двух работ, отбор, создание, переименование и удаление', async ({
  page,
}) => {
  test.setTimeout(300_000)
  await signUpAndLogin(page, 'reportlist')

  const курсовая = await завести(
    page,
    КУРСОВАЯ,
    бланк('бланк-первый', ['Отчёт', `{{${ТЕГ_ОДИН}:${ОПИСАНИЕ_ОДИН}}}`, КОНСТРУКЦИЯ]),
  )

  // ── в работе пишут ДО того, как в ней завели первый отчёт ─────────────────
  // Так работа и живёт: бланк выбран при создании, теги заполняются сразу, а
  // до второго документа дело доходит позже. Собственный документ работы
  // открывается адресом без отчёта.
  await page.goto(`/reports/${курсовая}`)
  const поле_один = page.getByRole('textbox', {
    name: t('reports.editor.field', { tag: ТЕГ_ОДИН }),
  })
  await expect(поле_один).toBeVisible({ timeout: 30_000 })
  await поле_один.fill(ЗНАЧЕНИЕ_ОДИН)
  await page.getByRole('button', { name: t('common.action.save'), exact: true }).click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 1 }))).toBeVisible({
    timeout: 30_000,
  })

  // ── главная отчётов: пока пусто, и та же кнопка стоит в пустом состоянии ──
  await page.goto('/reports')
  await expect(page.getByText(t('reports.list.emptyTitle'))).toBeVisible({ timeout: 30_000 })

  // ── 2, 7. первый отчёт: собственный документ работы, её же бланк ──────────
  await page
    .getByRole('button', { name: t('reports.list.create') })
    .first()
    .click()
  let окно = page.getByRole('dialog')
  // Работа в пространстве одна и выбрана сама.
  await expect(окно.getByLabel(t('reports.list.projectLabel'))).toHaveValue(курсовая)
  await окно.getByLabel(t('reports.list.nameLabel')).fill(ИМЯ_ОДИН)
  await окно.getByRole('button', { name: t('reports.list.createAction') }).click()
  await expect(page).toHaveURL(new RegExp(`/reports/${курсовая}/[0-9a-f-]{36}`), {
    timeout: 30_000,
  })

  // 7. Первый отчёт открыл документ работы: бланк её, и написанное на месте.
  await expect(поле_один).toHaveValue(ЗНАЧЕНИЕ_ОДИН, { timeout: 30_000 })

  // Тег назван описанием, ключ стоит под ним и без фигурных скобок.
  const строка_тега = page.getByRole('button', { name: ОПИСАНИЕ_ОДИН })
  await expect(строка_тега).toBeVisible({ timeout: 30_000 })
  await expect(строка_тега).toContainText(ТЕГ_ОДИН)
  await expect(строка_тега).not.toContainText('{{')

  // Конструкция названа числом, а список свёрнут.
  const конструкции = page
    .locator('details')
    .filter({ hasText: t('reports.tags.unknownConstructs', { n: 1 }) })
  await expect(конструкции).toBeVisible()
  await expect(конструкции.getByText(КОНСТРУКЦИЯ)).toBeHidden()
  await конструкции.locator('summary').click()
  await expect(конструкции.getByText(КОНСТРУКЦИЯ)).toBeVisible()

  // ── вторая работа: без бланка, бланк приложится прямо в окне создания ─────
  const практика = await завести(page, ПРАКТИКА)

  await page.goto('/reports')
  await page
    .getByRole('button', { name: t('reports.list.create') })
    .first()
    .click()
  окно = page.getByRole('dialog')
  // 2. Работа называется в окне: главная больше не спрашивает её заранее.
  await окно.getByLabel(t('reports.list.projectLabel')).selectOption(практика)
  await окно.getByLabel(t('reports.list.nameLabel')).fill(ИМЯ_ДВА)
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
  await expect(page).toHaveURL(new RegExp(`/reports/${практика}/[0-9a-f-]{36}`), {
    timeout: 30_000,
  })

  // 3. Теги у второго отчёта свои, и значения первого сюда не приехали.
  const поле_два = page.getByRole('textbox', { name: t('reports.editor.field', { tag: ТЕГ_ДВА }) })
  await expect(поле_два).toBeVisible({ timeout: 30_000 })
  await expect(поле_два).toHaveValue('')
  await expect(page.getByRole('button', { name: ОПИСАНИЕ_ОДИН })).toHaveCount(0)
  await поле_два.fill(ЗНАЧЕНИЕ_ДВА)
  await page.getByRole('button', { name: t('common.action.save'), exact: true }).click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 1 }))).toBeVisible({
    timeout: 30_000,
  })

  // ── 5. сборка кладёт первую страницу картинкой ────────────────────────────
  // Кнопка сборки стоит и в шапке колонки превью, и в её пустом состоянии:
  // пока превью не собрано, их две, и нужна любая.
  await page
    .getByRole('button', { name: t('reports.pdf.build'), exact: true })
    .first()
    .click()
  await expect(page.getByRole('link', { name: t('reports.pdf.downloadPdf') })).toBeVisible({
    timeout: 180_000,
  })

  // ── 1. отчёты обеих работ стоят в одном списке ────────────────────────────
  await page.goto('/reports')
  const карточки = page.getByTestId('report-cards')
  const карточка_два = карточки.getByRole('listitem').filter({ hasText: ИМЯ_ДВА })
  const карточка_один = карточки.getByRole('listitem').filter({ hasText: ИМЯ_ОДИН })
  await expect(карточка_один).toHaveCount(1, { timeout: 30_000 })
  await expect(карточка_два).toHaveCount(1)
  // Каждый назван своей работой — ссылкой на неё.
  await expect(карточка_один.getByRole('link', { name: КУРСОВАЯ })).toHaveAttribute(
    'href',
    `/projects/${курсовая}`,
  )
  await expect(карточка_два.getByRole('link', { name: ПРАКТИКА })).toBeVisible()

  // 5. Картинка хранится, а не рисуется на лету: перезагрузка её не теряет.
  await expect(карточка_два.locator('img')).toBeVisible({ timeout: 60_000 })
  await page.reload()
  await expect(карточка_два.locator('img')).toBeVisible({ timeout: 60_000 })

  // ── 4. отбор по работе встаёт в адрес, поиск сужает список ────────────────
  await page.getByLabel(t('reports.home.filterProject')).selectOption(практика)
  await expect(page).toHaveURL(new RegExp(`/reports\\?project=${практика}$`))
  await expect(карточка_один).toHaveCount(0)
  await expect(карточка_два).toHaveCount(1)

  await page.getByLabel(t('reports.home.filterProject')).selectOption('')
  await expect(карточка_один).toHaveCount(1)
  // Поиск помнит и работу: имя работы находит её отчёт.
  await page.getByLabel(t('reports.home.search')).fill(КУРСОВАЯ)
  await expect(карточка_два).toHaveCount(0)
  await expect(карточка_один).toHaveCount(1)
  await page.getByLabel(t('reports.home.search')).fill('')

  // ── 6. удаление сносит один отчёт, сосед остаётся целым ───────────────────
  await карточка_два
    .getByRole('button', { name: t('reports.list.deleteAction', { name: ИМЯ_ДВА }) })
    .click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: t('reports.list.delete'), exact: true })
    .click()
  await expect(карточка_два).toHaveCount(0, { timeout: 30_000 })
  await expect(карточка_один).toHaveCount(1)

  // ── 8. переименование прямо на карточке списка ────────────────────────────
  // Карандаш стоит у имени; поле правки встаёт на место имени, поэтому дальше
  // отбирать карточку по прежнему тексту нельзя — поле ищется по всей странице.
  await карточка_один
    .getByRole('button', { name: t('projects.runs.rename', { name: ИМЯ_ОДИН }) })
    .click()
  const поле_имени = page.getByRole('textbox', {
    name: t('projects.runs.rename', { name: ИМЯ_ОДИН }),
  })
  await поле_имени.fill(ИМЯ_ОДИН_НОВОЕ)
  await поле_имени.press('Enter')
  const карточка_новая = карточки.getByRole('listitem').filter({ hasText: ИМЯ_ОДИН_НОВОЕ })
  await expect(карточка_новая).toHaveCount(1, { timeout: 30_000 })

  // Имя одно на все места: журнал работы знает его тем же запросом.
  await page.goto(`/projects/${курсовая}`)
  await expect(page.getByRole('link', { name: ИМЯ_ОДИН_НОВОЕ })).toBeVisible({ timeout: 30_000 })

  // ...и заголовок экрана отчёта, куда ведёт карточка. Значение, написанное в
  // работе до отчётов, всё это время лежит там же.
  await page.goto('/reports')
  await карточка_новая.getByRole('link').first().click()
  await expect(page.getByRole('heading', { name: ИМЯ_ОДИН_НОВОЕ })).toBeVisible({
    timeout: 30_000,
  })
  await expect(
    page.getByRole('textbox', { name: t('reports.editor.field', { tag: ТЕГ_ОДИН }) }),
  ).toHaveValue(ЗНАЧЕНИЕ_ОДИН, { timeout: 30_000 })
})
