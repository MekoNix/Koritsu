/**
 * Много решений в одной работе: свои условия, свои папки контекста, удаление.
 *
 * Работа держит материалы, артефакты и потолок расхода, а решений в ней
 * столько, сколько задач задали. До этого состояние решения было одно на
 * работу, и вторая задача в ней затирала первую — молча, вместе с условием,
 * пожеланиями и списком блоков. Проверяется наблюдаемым:
 *
 * 1. **Два решения в одной работе живут врозь.** Условие второго не подменяет
 *    условия первого, и наоборот.
 * 2. **Папка контекста своя у каждого.** Файл, положенный в одно решение, во
 *    втором не виден вовсе: в промпт решения уезжают только его файлы, и чужая
 *    методичка сбивает модель ровно так же, как чужое условие.
 * 3. **`required_kinds`, не совпавшие с именами разделов, не роняют прогон.**
 *    Модель называет один и тот же раздел дважды — заголовком в `sections` и
 *    своими словами в `required_kinds`; строгая сверка роняла на этом целый
 *    прогон, за который уже заплачено. Теперь имена сопоставляются по близости,
 *    несопоставленное отбрасывается замечанием, и семь стадий доходят до конца.
 *    Поддельная модель сочиняет `required_kinds` из схемы, то есть именами, с
 *    разделами не совпадающими, — ровно тот случай.
 * 4. **Удаление одного решения не трогает второе.** Ни его ход стадий, ни его
 *    условие, ни его файлы.
 */
import { expect, test } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'

const УСЛОВИЕ_1 = 'Задача 1. Написать программу, считающую сумму чисел от 1 до n, и оформить отчёт.'
const УСЛОВИЕ_2 = 'Задача 2. Посчитать количество слов в строке и построить блок-схему.'

/** Состояние стадии — значение службы (`kadai.stages`), оно же в `data-state`. */
const СДЕЛАНО = 'сделано'

test('решения: два в одной работе, свои файлы, удаление второго не трогает первое', async ({
  page,
}) => {
  test.setTimeout(240_000)
  await signUpAndLogin(page, 'kadai-runs')

  // ── работа заводится один раз, решений в ней будет два ────────────────────
  await page.getByRole('link', { name: t('shell.nav.kadai'), exact: true }).click()
  await expect(page.getByRole('heading', { name: t('kadai.home.title') })).toBeVisible()
  await page
    .getByRole('button', { name: t('kadai.home.newWork') })
    .first()
    .click()
  await page.getByLabel(t('kadai.new.workName')).fill('Две задачи')
  await page.getByRole('button', { name: t('kadai.home.newWorkSubmit'), exact: true }).click()
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/new$/)
  const projectId = (page.url().match(/kadai\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // ── первое решение: своё условие и своя методичка ─────────────────────────
  await завести(page, 'Первая задача', УСЛОВИЕ_1, 'первая-методичка.txt', 'Оформление: ГОСТ.')
  const первое = решениеИзАдреса(page)

  // Папка контекста показывает свой файл и условие — и ничего больше.
  await expect(page.getByTestId('kadai-context-list')).toContainText('первая-методичка.txt', {
    timeout: 60_000,
  })
  await expect(page.getByTestId('kadai-context-list')).not.toContainText('вторая-методичка.txt')

  // ── второе решение в той же работе ────────────────────────────────────────
  await page.goto(`/kadai/${projectId}`)
  await page
    .getByRole('button', { name: t('kadai.home.create') })
    .first()
    .click()
  await expect(page).toHaveURL(new RegExp(`/kadai/${projectId}/new$`))
  await завести(page, 'Вторая задача', УСЛОВИЕ_2, 'вторая-методичка.txt', 'Данные: строка;слов')
  const второе = решениеИзАдреса(page)
  expect(второе).not.toBe(первое)

  // Условие второго — своё, а не первого: состояние решения больше не одно на
  // работу.
  await expect(page.getByText('количество слов в строке', { exact: false })).toBeVisible({
    timeout: 60_000,
  })
  await expect(page.getByText('сумму чисел от 1 до n', { exact: false })).toHaveCount(0)

  // И папка контекста — своя: файла соседней задачи здесь нет вовсе.
  await expect(page.getByTestId('kadai-context-list')).toContainText('вторая-методичка.txt', {
    timeout: 60_000,
  })
  await expect(page.getByTestId('kadai-context-list')).not.toContainText('первая-методичка.txt')

  // ── прогон первого решения доходит до конца ───────────────────────────────
  // Поддельная модель объявляет обязательными виды разделов, имена которых с её
  // же разделами не совпадают. Раньше строгая сверка роняла на этом прогон;
  // теперь имена сопоставляются по близости, и стадии идут дальше.
  await page.goto(`/kadai/${projectId}/${первое}`)
  await expect(page.getByText('сумму чисел от 1 до n', { exact: false })).toBeVisible({
    timeout: 60_000,
  })
  await page.getByRole('button', { name: t('kadai.condition.ok') }).click()
  const решить = page.getByRole('button', { name: t('kadai.run.start') })
  await expect(решить).toBeEnabled()
  await решить.click()
  await expect(page.locator(`[data-stage="архив"][data-state="${СДЕЛАНО}"]`)).toBeVisible({
    timeout: 180_000,
  })
  // Прогон не встал: строки «стадия споткнулась» на экране нет.
  await expect(page.getByText(t('kadai.run.restartHint'))).toHaveCount(0)

  // ── удаление второго решения не трогает первое ────────────────────────────
  await page.goto(`/kadai/${projectId}`)
  const карточки = page.getByTestId('kadai-runs').getByRole('listitem')
  await expect(карточки).toHaveCount(2)
  await карточки
    .filter({ hasText: 'Вторая задача' })
    .getByRole('button', { name: t('common.action.delete') })
    .click()
  await expect(карточки).toHaveCount(1)
  await expect(карточки.first()).toContainText('Первая задача')

  // Первое решение осталось целым: его ход стадий, его условие и его файл.
  await page.goto(`/kadai/${projectId}/${первое}`)
  await expect(page.locator(`[data-stage="архив"][data-state="${СДЕЛАНО}"]`)).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('сумму чисел от 1 до n', { exact: false })).toBeVisible()
  await expect(page.getByTestId('kadai-context-list')).toContainText('первая-методичка.txt')
})

/**
 * Заполнить страницу нового решения и завести его.
 *
 * Условие текстом, а не файлом: разбор `.txt` — одна строка работы очереди, и
 * ждать его на стенде дешевле всего. Приёмник файлов на этой странице ровно
 * один — поле условия при выборе «текстом» не рисуется.
 */
async function завести(
  page: import('@playwright/test').Page,
  имя: string,
  условие: string,
  файл: string,
  содержимое: string,
): Promise<void> {
  await page.getByLabel(t('kadai.new.name')).fill(имя)
  await page.getByRole('radio', { name: t('kadai.new.byText') }).check()
  await page.getByLabel(t('kadai.new.textLabel')).fill(условие)
  await page
    .locator('input[type="file"]')
    .setInputFiles([{ name: файл, mimeType: 'text/plain', buffer: Buffer.from(содержимое) }])
  await expect(page.getByText(файл)).toBeVisible()
  await page.getByRole('button', { name: t('kadai.new.submit'), exact: true }).click()
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/)
}

/** Идентификатор решения из адреса экрана решения. */
function решениеИзАдреса(page: import('@playwright/test').Page): string {
  const части = page.url().match(/kadai\/([0-9a-f-]{36})\/([0-9a-f-]{36})/) as RegExpMatchArray
  return части[2] as string
}
