/**
 * Пространство разделяет работу — и на экране это видно.
 *
 * Проверка держит два правила, оба из которых ломаются молча и оба из которых
 * человек замечает не сразу, а когда уже запутался:
 *
 * 1. **в одном пространстве не видно работ другого.** Списки, главные модулей и
 *    поиск спрашивают службу с текущим пространством, и служба без него не
 *    отвечает вовсе. Сломать это легко — достаточно одного списка, забывшего
 *    отбор, — а увидеть можно только заведя два пространства и сравнив;
 * 2. **работа из другого пространства открывается, но не молча.** Ссылка на
 *    неё законная (из письма, из закладки), и запрещать её нечего; но человек
 *    обязан узнать, что смотрит не туда, где сейчас работает, — и переключиться
 *    одним нажатием, а не искать переключатель в сайдбаре.
 *
 * Отдельно — тосты отказа: у каждого кода службы две строки, «что случилось» и
 * «что делать». Отказ здесь подделан перехватом ответа (`page.route`), а не
 * вызван настоящей бедой, и это единственный способ проверить оба случая сразу:
 * знакомый код показывается по-русски, незнакомый — общим текстом с английским
 * сообщением службы и номером запроса мелкой строкой. Настоящей беды с
 * незнакомым кодом у службы нет по определению: как только код заводят, к нему
 * пишут перевод (`src/api/errors.test.ts`).
 *
 * Прогонов модели ни одного: ни списки, ни поиск, ни тосты её не зовут.
 */
import { expect, test } from '@playwright/test'

import { nicknameFor, перейти, signUpAndLogin, t } from './helpers'

const КАФЕДРА = 'Кафедра ИУ7'
const ЛИЧНАЯ = 'Работа личная'
const КАФЕДРАЛЬНАЯ = 'Работа кафедры'

/** Завести работу в текущем пространстве. → её идентификатор. */
async function завести(page: import('@playwright/test').Page, имя: string): Promise<string> {
  await перейти(page, '/projects')
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('projects.create.name')).fill(имя)
  await окно.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  return (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string
}

test('в другом пространстве чужих работ не видно, а открытая по ссылке зовёт переключиться', async ({
  page,
}) => {
  test.setTimeout(180_000)
  const почта = await signUpAndLogin(page, 'scope')
  const ник = nicknameFor(почта)

  const личная = await завести(page, ЛИЧНАЯ)

  // ── второе пространство ───────────────────────────────────────────────────
  const переключатель = page.getByRole('button', { name: t('workspace.switcher.label') })
  await переключатель.click()
  await page.getByRole('menuitem', { name: t('workspace.switcher.create') }).click()
  const создание = page.getByRole('dialog', { name: t('workspace.create.title') })
  await создание.getByLabel(t('workspace.create.name')).fill(КАФЕДРА)
  await создание.getByRole('button', { name: t('workspace.create.submit') }).click()
  await expect(переключатель).toContainText(КАФЕДРА, { timeout: 30_000 })

  const кафедральная = await завести(page, КАФЕДРАЛЬНАЯ)

  // ── список работ: только своё пространство, и оно названо ─────────────────
  await перейти(page, '/projects')
  await expect(page.getByRole('link', { name: КАФЕДРАЛЬНАЯ })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('link', { name: ЛИЧНАЯ })).toHaveCount(0)
  // Подпись над списком отвечает на «где эти работы лежат». Спрашиваем
  // содержимое страницы, а не всю её: имя пространства стоит ещё и в
  // переключателе, и «где-то на экране написано „Кафедра“» ничего не доказывает.
  await expect(page.getByRole('main').getByText(КАФЕДРА).first()).toBeVisible()
  // И в самой строке работы: список читают прокрученным и пересылают снимком
  // экрана, где шапки с подписью уже нет.
  await expect(page.getByRole('listitem').filter({ hasText: КАФЕДРАЛЬНАЯ })).toContainText(КАФЕДРА)

  // ── главная отчётов: отбор по работе — из текущего пространства ───────────
  // Отчётов здесь ещё нет, и работы видны только отбором над сеткой — по нему
  // и проверяется, что чужое пространство сюда не попало. Спрашивается состав
  // списка, а не видимость: свёрнутый родной `<select>` своих строк не
  // показывает.
  await перейти(page, '/reports')
  const отбор = page.getByLabel(t('reports.home.filterProject'))
  await expect(отбор).toBeVisible({ timeout: 30_000 })
  await expect(отбор.locator('option', { hasText: КАФЕДРАЛЬНАЯ })).toHaveCount(1)
  await expect(отбор.locator('option', { hasText: ЛИЧНАЯ })).toHaveCount(0)

  // ── главная блок-схем: работа в пространстве одна, и выбирать не из чего ──
  await перейти(page, '/flowcharts')
  // Кнопка «Новая схема» стоит и в шапке, и в пустом состоянии списка —
  // на пустой главной их две, и нужна любая.
  await page
    .getByRole('button', { name: t('diagrams.home.new') })
    .first()
    .click()
  // Работ было бы две — открылось бы меню выбора; одна ведёт прямо в работу.
  await expect(page).toHaveURL(new RegExp(`/flowcharts/${кафедральная}$`), { timeout: 30_000 })

  // ── поиск: чужого не находит ──────────────────────────────────────────────
  await перейти(page, '/')
  const кнопка = page.getByRole('button').filter({ hasText: t('shell.search.label') })
  await expect(кнопка).toBeVisible()
  await page.keyboard.press('Control+k')
  const палитра = page.getByRole('dialog', { name: t('search.title') })
  await expect(палитра).toBeVisible()
  const поле = палитра.getByPlaceholder(t('search.placeholder'))

  await поле.fill('кафедры')
  await expect(палитра.getByRole('option', { name: new RegExp(КАФЕДРАЛЬНАЯ) })).toBeVisible({
    timeout: 30_000,
  })

  await поле.fill('личная')
  await expect(палитра.getByText(t('search.nothing', { query: 'личная' }))).toBeVisible({
    timeout: 30_000,
  })
  await page.keyboard.press('Escape')

  // ── работа другого пространства по адресу ─────────────────────────────────
  await перейти(page, `/projects/${личная}`)
  await expect(page.getByRole('heading', { name: ЛИЧНАЯ })).toBeVisible({ timeout: 30_000 })
  // Не молча: полоска называет пространство работы и предлагает переключиться.
  // Имя личного пространства служба складывает из ника (`<ник>-workspace`),
  // поэтому спрашиваем вхождение ника, а не строку целиком.
  const полоска = page.locator('[role="status"]').filter({ hasText: t('workspace.other.hint') })
  await expect(полоска).toBeVisible({ timeout: 30_000 })
  await expect(полоска).toContainText(ник)
  await полоска.getByRole('button', { name: t('workspace.other.switch') }).click()

  // Переключились — и теперь всё вокруг про то же пространство, что и работа.
  await expect(переключатель).toContainText(ник, { timeout: 30_000 })
  await expect(полоска).toHaveCount(0)
  await перейти(page, '/projects')
  await expect(page.getByRole('link', { name: ЛИЧНАЯ })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('link', { name: КАФЕДРАЛЬНАЯ })).toHaveCount(0)
})

test('тост отказа говорит, что случилось и что делать, а незнакомый код — с номером запроса', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await signUpAndLogin(page, 'toastcode')

  const переключатель = page.getByRole('button', { name: t('workspace.switcher.label') })

  /**
   * Ответить на заведение пространства подделанным отказом.
   *
   * Номер запроса берётся латиницей: он едет заголовком HTTP, а заголовок —
   * это байты latin-1, и кириллица в нём приезжает в браузер испорченной.
   * Служба и выдаёт его латиницей, так что подделка здесь честная.
   */
  const отказ = async (code: string, message: string, rid: string) => {
    await page.route('**/api/workspaces', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        headers: { 'X-Request-Id': rid },
        body: JSON.stringify({ error: { code, message } }),
      })
    })
  }

  const завести_пространство = async (имя: string) => {
    await переключатель.click()
    await page.getByRole('menuitem', { name: t('workspace.switcher.create') }).click()
    const окно = page.getByRole('dialog', { name: t('workspace.create.title') })
    await окно.getByLabel(t('workspace.create.name')).fill(имя)
    await окно.getByRole('button', { name: t('workspace.create.submit') }).click()
  }

  // ── знакомый код: две строки по-русски ────────────────────────────────────
  await отказ('quota_exceeded', 'Storage quota exceeded', 'rid-known')
  await завести_пространство('Первое')
  // Тост ищется селектором, а не ролью: пока открыто модальное окно, Radix
  // прячет от дерева доступности всё, что снаружи него, — а лента тостов как
  // раз снаружи.
  const тост = page.locator('[role="status"]').filter({ hasText: t('errors.quota_exceeded.what') })
  await expect(тост).toBeVisible({ timeout: 30_000 })
  // Что делать — вторая строка, а не догадка человека.
  await expect(тост).toContainText(t('errors.quota_exceeded.next'))
  // Номер запроса есть и у знакомого кода: по нему жалобу находят в журнале.
  await expect(тост).toContainText('rid-known')
  // Английского текста службы человек не видит: он написан не для него.
  await expect(тост).not.toContainText('Storage quota exceeded')

  await page.unroute('**/api/workspaces')
  await page.reload()

  // ── незнакомый код: общий текст плюс подробности мелкой строкой ───────────
  await отказ('код_из_будущего', 'Something new happened', 'rid-unknown')
  await завести_пространство('Второе')
  const второй = page.locator('[role="status"]').filter({ hasText: t('errors.unknown.what') })
  await expect(второй).toBeVisible({ timeout: 30_000 })
  await expect(второй).toContainText(t('errors.unknown.next'))
  // Молчать нельзя, а выдумывать перевод нечестно: показывается то, что сказала
  // служба, и то, чем эту жалобу найдут в её журнале.
  await expect(второй).toContainText('Something new happened')
  await expect(второй).toContainText('rid-unknown')
})
