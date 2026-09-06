/**
 * Модуль «Решения» браузером: правка условия, файлы контекста, журнал работы,
 * отсутствие цен и превью до первой сборки.
 *
 * Каждый шаг сторожит решение, которое иначе тихо возвращается назад.
 *
 * 1. **Условие правится и очищается.** Поле заводилось из распознанного текста
 *    наблюдением за пустотой черновика, и стёртый текст тут же подставлялся
 *    обратно: Ctrl+A и Delete не давали ничего. Проверяется наблюдаемым —
 *    поле остаётся пустым после очистки, а не «код выглядит правильно».
 * 2. **Цены и остатка до нажатия нет нигде.** Цена прогона динамическая, и
 *    названное заранее число было бы обещанием, которого никто не давал.
 *    Проверяется грепом по тексту страницы на всех экранах, где цена стояла:
 *    решения, отчёты, дашборд, окно агента, выгрузка работы.
 * 3. **Превью «как будет в Word» появляется только после первой сборки.** До
 *    неё вкладки нет вовсе: пустая рамка с кнопкой выглядела ожиданием того,
 *    чего в работе ещё не существует.
 * 4. **Решение попадает в журнал работы.** Заведённое из модуля — так же, как
 *    заведённое из карточки работы (`runs.spec.ts`): запись ставится в момент
 *    заведения, а не когда-нибудь потом.
 * 5. **Файлы контекста кладутся на странице нового запуска, все разом.**
 *
 * Прогон модели здесь не запускается вовсе: всё перечисленное видно до него, а
 * семь стадий на подделке уже проверены (`kadai.spec.ts`).
 */
import { expect, test } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'

const УСЛОВИЕ = 'Задача 2. Посчитать количество слов в строке и оформить работу.'

/** Строка цены, которой на экранах больше нет ни в каком виде. */
const ЦЕНА = /Стоит\s+\d/

test('решения: условие правится и очищается, цен нет, превью — только после сборки', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await signUpAndLogin(page, 'solutions')

  // ── 1. модуль называется «Решения» ────────────────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.kadai'), exact: true }).click()
  await expect(page.getByRole('heading', { name: t('kadai.home.title') })).toBeVisible()
  expect(t('kadai.home.title')).toBe(t('shell.nav.kadai'))

  // ── 2. заведение работы: условие текстом и файлы контекста разом ──────────
  // Работа и решение заводятся по очереди: работа держит материалы и потолок
  // расхода, а решений в ней столько, сколько задач задали.
  await page
    .getByRole('button', { name: t('kadai.home.newWork') })
    .first()
    .click()
  await page.getByLabel(t('kadai.new.workName')).fill('Слова в строке')
  await page.getByRole('button', { name: t('kadai.home.newWorkSubmit'), exact: true }).click()
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/new$/)
  await page.getByRole('radio', { name: t('kadai.new.byText') }).check()
  await page.getByLabel(t('kadai.new.textLabel')).fill(УСЛОВИЕ)

  // Файлы контекста — приёмник на несколько файлов сразу: методичка и данные
  // нужны работе целиком, и раскладывать их по разделам человеку нечем.
  await page.locator('input[type="file"]').setInputFiles([
    { name: 'методичка.txt', mimeType: 'text/plain', buffer: Buffer.from('Оформление: ГОСТ.') },
    { name: 'данные.txt', mimeType: 'text/plain', buffer: Buffer.from('строка;слов\nа б;2') },
  ])
  await expect(page.getByText('методичка.txt')).toBeVisible()
  await expect(page.getByText('данные.txt')).toBeVisible()

  // Цены нет уже здесь — на экране, где раньше она стояла у кнопки «Завести».
  await expect(page.getByText(ЦЕНА)).toHaveCount(0)

  await page.getByRole('button', { name: t('kadai.new.submit'), exact: true }).click()
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/kadai\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // ── 3. условие: правится, очищается и сохраняется ────────────────────────
  await expect(page.getByText('количество слов в строке', { exact: false })).toBeVisible({
    timeout: 30_000,
  })
  await page.getByRole('button', { name: t('kadai.condition.fix') }).click()
  const поле = page.getByLabel(t('kadai.condition.title'))
  await expect(поле).toHaveValue(/количество слов/)

  // Очистка с клавиатуры — тем же способом, каким её делает человек.
  await поле.click()
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Delete')
  // Пустым поле и остаётся: подставлять распознанное второй раз некому.
  await expect(поле).toHaveValue('')
  await expect(page.getByText(t('kadai.condition.emptyDraft'))).toBeVisible()
  await expect(page.getByRole('button', { name: t('kadai.condition.save') })).toBeDisabled()

  // И принимает новый текст на место стёртого.
  await поле.fill('Задача 2. Посчитать слова, считая дефис частью слова.')
  await page.getByRole('button', { name: t('kadai.condition.save') }).click()
  await expect(page.getByText('считая дефис частью слова', { exact: false })).toBeVisible({
    timeout: 60_000,
  })

  // ── 4. превью «как будет в Word» до сборки не показывается ────────────────
  // Ни вкладки, ни рамки: работа ещё не собиралась, и ждать нечего.
  await expect(page.getByRole('radio', { name: t('kadai.tabs.preview') })).toHaveCount(0)
  await expect(page.locator('embed[type="application/pdf"]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: t('reports.pdf.build') })).toHaveCount(0)

  // ── 5. цен и остатка на экране работы нет ────────────────────────────────
  await expect(page.getByText(ЦЕНА)).toHaveCount(0)
  await expect(page.getByText(/осталось/)).toHaveCount(0)

  // ── 6. решение попало в журнал работы ────────────────────────────────────
  await page.goto(`/projects/${projectId}`)
  const запись = t('projects.runs.autoName', {
    unit: t('projects.runs.unit.kadai'),
    n: 1,
    project: 'Слова в строке',
  })
  await expect(page.getByText(запись)).toBeVisible({ timeout: 30_000 })
  // Файлы контекста доехали в опись работы той же очередью, что и условие.
  // `first()`: имя файла на странице работы стоит дважды — строкой описи и
  // подписью карточки материала, и обе видны разом.
  await expect(page.getByText('методичка.txt').first()).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('данные.txt').first()).toBeVisible()

  // ── 7. цен нет и на остальных экранах, где они стояли ────────────────────
  // Выгрузка работы: цена стояла над кнопкой «Выгрузить».
  await page.getByRole('button', { name: t('projects.export.action') }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText(ЦЕНА)).toHaveCount(0)
  await page.keyboard.press('Escape')

  // Окно агента: цена стояла у выбора модели.
  await page.keyboard.press('Control+j')
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText(ЦЕНА)).toHaveCount(0)
  await page.keyboard.press('Escape')

  // Дашборд: цена стояла в плитке «Word → PDF». Расход в своём виджете
  // остаётся — это не цена до нажатия, а сколько уже потрачено.
  await page.goto('/')
  await expect(page.getByText(t('dashboard.wordToPdf.title'))).toBeVisible()
  await expect(page.getByText(ЦЕНА)).toHaveCount(0)
})
