/**
 * Боевая сборка в браузере: открывается ли собранный `dist` и грузятся ли его
 * куски.
 *
 * **Нужен собранный `dist`.** Проверка не поднимает дев-сервер и ничего не
 * собирает — она ходит по статике, отданной как в бою:
 *
 *     cd web
 *     VITE_BASE_PATH=<префикс> pnpm build
 *     pnpm e2e:dist
 *
 * Настройка — `playwright.dist.config.ts` (там же и про то, откуда берётся
 * префикс пути); обычный `pnpm e2e` эту проверку не подбирает.
 *
 * **Зачем она.** У боевой сборки есть четыре свойства, которых нет ни у одной
 * другой проверки: деление на куски, ленивые `import()` по областям сайта,
 * обфускация и префикс пути. Ломаются они вместе и молча: браузер просит кусок
 * не по тому адресу, получает `index.html`, и область сайта не открывается
 * вовсе — при том что страница входа, приехавшая первым куском, работает. Ни
 * `pnpm test`, ни `pnpm e2e` этого не видят: в них сборки нет.
 *
 * Поэтому здесь не проверяется поведение — оно проверено в других местах.
 * Здесь проверяется, что **каждый экран вообще открылся**, а браузер по дороге
 * не пожаловался ни на один кусок: вход → дашборд → проект → отчёт → схема.
 * Это те пять областей, у каждой из которых свой ленивый кусок.
 */
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

import { signUpAndLogin, t, templateDocx, перейти } from './helpers'

const РАБОТА = 'Боевая сборка'

/**
 * Жалобы браузера, собранные за прогон.
 *
 * Три источника, и все три нужны: не загрузившийся кусок виден как `requestfailed`
 * либо как ответ 404 на `assets/…`, а сломанный обфускацией код — как
 * необработанное исключение (`pageerror`) и запись в консоли.
 */
type Жалобы = { сообщения: string[] }

function слушать(page: Page): Жалобы {
  const жалобы: Жалобы = { сообщения: [] }
  page.on('console', (msg) => {
    if (msg.type() === 'error') жалобы.сообщения.push(`консоль: ${msg.text()}`)
  })
  page.on('pageerror', (err) => жалобы.сообщения.push(`исключение: ${err.message}`))
  page.on('requestfailed', (req) => {
    const беда = req.failure()?.errorText ?? '—'
    // `ERR_ABORTED` — это не беда, а уход со страницы: браузер снимает всё, что
    // не доехало, а поток заданий (`/api/events`) закрывается на каждом
    // переходе по устройству. Считать это поломкой значило бы иметь проверку,
    // которая краснеет ровно от того, что человек ходит по сайту.
    if (беда.includes('ERR_ABORTED')) return
    жалобы.сообщения.push(`запрос не удался: ${req.url()} (${беда})`)
  })
  page.on('response', (res) => {
    if (res.status() >= 400 && /\/assets\//.test(res.url())) {
      жалобы.сообщения.push(`кусок ${res.url()} — ${res.status()}`)
    }
  })
  return жалобы
}

/**
 * Заглушки чужих доменов: у стенда нет сети, а встроенный кадр draw.io живёт
 * снаружи. Без заглушки каждый заход на схемы ждал бы сеть до отказа, и в
 * жалобах браузера лежала бы не наша беда.
 */
async function подменить_drawio(context: BrowserContext): Promise<void> {
  for (const домен of ['https://app.diagrams.net/**', 'https://viewer.diagrams.net/**']) {
    await context.route(домен, (route) =>
      route.fulfill({ contentType: 'text/html', body: '<html><body>drawio</body></html>' }),
    )
  }
}

test('боевая сборка: экраны открываются, куски грузятся', async ({ page, context }) => {
  test.setTimeout(180_000)
  await подменить_drawio(context)
  const жалобы = слушать(page)

  // Куски, что браузер действительно забрал. Пустой список означал бы, что
  // проверка ходит не по сборке, — например по дев-серверу.
  const куски: string[] = []
  page.on('response', (res) => {
    if (res.ok() && /\/assets\/.*\.js$/.test(res.url())) куски.push(res.url())
  })

  // ── вход ──────────────────────────────────────────────────────────────────
  // Первый же экран — уже проверка: разметка, стили и первый кусок приехали
  // из `dist` под префиксом пути.
  await signUpAndLogin(page, 'dist')

  // ── дашборд ───────────────────────────────────────────────────────────────
  await перейти(page, '/')
  await expect(page.locator('h1').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('link', { name: t('shell.nav.projects') })).toBeVisible()

  // ── проект ────────────────────────────────────────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await expect(page.getByRole('heading', { name: t('projects.list.title') })).toBeVisible()
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
  await expect(page.getByRole('heading', { name: РАБОТА })).toBeVisible()

  // ── отчёт ─────────────────────────────────────────────────────────────────
  // Теги приехали из шаблона — значит открылась не пустая рамка, а сам экран
  // со своим куском и своим запросом к службе.
  await перейти(page, `/reports/${projectId}`)
  await expect(page.getByText(t('reports.tags.counter', { filled: 0, total: 2 }))).toBeVisible({
    timeout: 60_000,
  })

  // ── схема ─────────────────────────────────────────────────────────────────
  // Здесь же проверяется самый тяжёлый кусок сборки — редактор кода: он лежит
  // отдельно (`codemirror`) и приезжает только на этом экране.
  await перейти(page, `/flowcharts/${projectId}`)
  const код = page.getByRole('textbox', { name: t('diagrams.work.codeLabel') })
  await expect(код).toBeVisible({ timeout: 60_000 })
  await код.click()
  await page.keyboard.insertText('def main():\n    x = 1\n    if x:\n        print(x)\n')
  // Первая схема на пустом экране строится сама; кнопка «скачать XML» оживает,
  // когда служба вернула построенное.
  await expect(page.getByRole('button', { name: t('diagrams.work.downloadXml') })).toBeEnabled({
    timeout: 90_000,
  })

  // ── итог ──────────────────────────────────────────────────────────────────
  // Кусков должно быть много: один — это признак того, что деление на части не
  // сработало, а ноль — что мы вообще не на сборке.
  expect(new Set(куски).size).toBeGreaterThan(3)
  expect(жалобы.сообщения, жалобы.сообщения.join('\n')).toEqual([])
})
