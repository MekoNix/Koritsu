/**
 * Схемы браузером: сама сохраняется, сама не перестраивается, открывается в
 * draw.io без потолка длины, удаляется из работы.
 *
 * Проверяется то, ради чего экран схем переделан, и в том же порядке:
 *
 * 1. **схема сохраняется сама** — построил и ушёл, а она уже в работе под
 *    именем «Схема 1 — <работа>», и это же имя стоит в журнале запусков;
 * 2. **правка кода картинку не трогает** — экран говорит, что код изменился, и
 *    ждёт кнопки; перестраивает только кнопка;
 * 3. **«Редактировать в draw.io» и «Просмотреть диаграмму»** ведут на
 *    `app.diagrams.net` и `viewer.diagrams.net`, и схемы в адресе нет вовсе:
 *    раньше она уезжала в `#R…`, и длинная схема гасила кнопку;
 * 4. **UML при входе не заводит файл** — сначала текст, потом запуск;
 * 5. **схема удаляется** из списка модуля, и запись журнала уходит вместе с ней.
 *
 * Домены draw.io подменяются заглушкой (`context.route`): сети у стенда нет, а
 * проверяем мы свой адрес, а не чужой редактор. Встроенный кадр при этом
 * честно окажется недоступен — экран обязан это пережить, и это проверяет
 * `flow.spec.ts`.
 */
import { expect, test, type BrowserContext } from '@playwright/test'

import { signUpAndLogin, t, templateDocx } from './helpers'

const РАБОТА = 'Схемы в работе'

const КОД = 'def main():\n    x = 1\n    if x:\n        print(x)\n'
const ДРУГОЙ_КОД = 'def other(n):\n    while n > 0:\n        n = n - 1\n    return n\n'

/** Имя, которое сайт рисует схеме без своего имени. */
function имяСхемы(module: string, n: number): string {
  return t('projects.runs.autoName', {
    unit: t(`projects.runs.unit.${module}`),
    n,
    project: РАБОТА,
  })
}

/**
 * Заглушки чужих доменов. Настоящий draw.io живёт в сети, которой у стенда
 * нет; нам важно, **куда** уходит окно и что в адресе нет схемы.
 */
async function подменить_drawio(context: BrowserContext): Promise<void> {
  for (const домен of ['https://app.diagrams.net/**', 'https://viewer.diagrams.net/**']) {
    await context.route(домен, (route) =>
      route.fulfill({ contentType: 'text/html', body: '<html><body>drawio</body></html>' }),
    )
  }
}

test('схемы: сохранение само, перестройка кнопкой, окна draw.io, удаление', async ({
  page,
  context,
}) => {
  await подменить_drawio(context)
  await signUpAndLogin(page, 'diagrams')

  // ── работа ────────────────────────────────────────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
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

  // ── 1. первая схема строится сама и сама сохраняется ──────────────────────
  await page.goto(`/flowcharts/${projectId}`)
  const код = page.getByRole('textbox', { name: t('diagrams.work.codeLabel') })
  await код.click()
  await page.keyboard.insertText(КОД)

  // Кнопку не нажимаем: первая схема на пустом экране строится сама — это
  // единственная самостоятельная постройка, что осталась.
  const сохранено = page.getByText(t('diagrams.work.savedAs', { name: имяСхемы('flowcharts', 1) }))
  await expect(сохранено).toBeVisible({ timeout: 60_000 })
  const xml = page.getByRole('button', { name: t('diagrams.work.downloadXml') })
  await expect(xml).toBeEnabled()

  // ── 2. правка кода картинку не перестраивает ──────────────────────────────
  await код.click()
  await page.keyboard.insertText(ДРУГОЙ_КОД)
  const устарело = page.getByText(t('diagrams.work.codeChanged'))
  await expect(устарело).toBeVisible()
  // Ждём дольше прежней задержки автообновления: если бы она осталась, схема
  // перестроилась бы сама и строка ушла бы без единого нажатия.
  await page.waitForTimeout(5000)
  await expect(устарело).toBeVisible()

  await page.getByRole('button', { name: t('diagrams.work.build') }).click()
  await expect(устарело).toBeHidden({ timeout: 60_000 })
  // Перестроилась та же схема: номер не вырос, второй записи в работе нет.
  await expect(сохранено).toBeVisible()

  // ── 3. окна draw.io: правильный адрес и никакого XML в нём ────────────────
  for (const [ключ, домен] of [
    ['diagrams.work.editInDrawio', 'app.diagrams.net'],
    ['diagrams.work.viewDiagram', 'viewer.diagrams.net'],
  ] as const) {
    const открытие = context.waitForEvent('page')
    await page.getByRole('button', { name: t(ключ) }).click()
    const окно_drawio = await открытие
    await окно_drawio.waitForLoadState('domcontentloaded')
    expect(окно_drawio.url()).toContain(домен)
    // Схема уезжает сообщением, а не адресом: потолка длины у адреса больше нет.
    expect(окно_drawio.url()).not.toContain('#R')
    expect(окно_drawio.url()).not.toContain('mxCell')
    expect(окно_drawio.url().length).toBeLessThan(300)
    await окно_drawio.close()
  }

  // ── 4. UML: при входе файла нет, схема появляется после запуска ───────────
  await page.goto(`/uml/${projectId}`)
  await expect(page.getByRole('heading', { name: t('diagrams.home.uml.title') })).toBeVisible()
  // Ни одного исходника: блок «Исходники» появляется вместе с первым файлом.
  await expect(page.getByText(t('diagrams.work.files'))).toHaveCount(0)
  await expect(page.getByRole('button', { name: t('diagrams.work.build') })).toBeDisabled()

  // ── 5. схема видна в списке модуля и в журнале работы ─────────────────────
  await page.goto('/flowcharts')
  const строка = page.getByRole('listitem').filter({ hasText: имяСхемы('flowcharts', 1) })
  await expect(строка).toHaveCount(1)

  await page.goto(`/projects/${projectId}`)
  await expect(page.getByText(имяСхемы('flowcharts', 1))).toBeVisible()

  // ── 6. удаление схемы ─────────────────────────────────────────────────────
  await page.goto('/flowcharts')
  await page
    .getByRole('button', { name: t('diagrams.home.remove', { name: имяСхемы('flowcharts', 1) }) })
    .click()
  await expect(page.getByText(имяСхемы('flowcharts', 1))).toHaveCount(0)

  // Запись журнала ушла вместе со схемой: удаление одно на обе.
  await page.goto(`/projects/${projectId}`)
  await expect(page.getByText(t('projects.runs.empty'))).toBeVisible()
})
