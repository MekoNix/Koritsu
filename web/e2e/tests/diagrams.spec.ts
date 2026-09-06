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
 * 4. **UML при входе не заводит файл** — список исходников пуст, и файл в нём
 *    появляется только от «Добавить файл»; убрать можно любой, включая
 *    последний, и тогда строить нечего;
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
  const сохранено = page.getByText(t('diagrams.work.savedAs'))
  await expect(сохранено).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(имяСхемы('flowcharts', 1))).toBeVisible()
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

  // ── 4. UML: файлов нет, пока их не завели, и любой из них можно убрать ────
  await page.goto(`/uml/${projectId}`)
  await expect(page.getByRole('heading', { name: t('diagrams.home.uml.title') })).toBeVisible()
  const построить = page.getByRole('button', { name: t('diagrams.work.build') })
  // Список исходников виден и пуст: `source.py` сам не заводится, и подсказка
  // объясняет, почему кнопка выключена.
  await expect(page.getByText(t('diagrams.work.files'))).toBeVisible()
  await expect(page.getByText(t('diagrams.work.noFiles'))).toBeVisible()
  await expect(page.getByText(t('diagrams.work.buildNeedsCode'))).toBeVisible()
  await expect(построить).toBeDisabled()
  // Поля кода тоже нет: править нечего, пока нет файла.
  await expect(page.getByRole('textbox', { name: t('diagrams.work.codeLabel') })).toHaveCount(0)

  // Два файла руками: имя спрашивается, язык берётся из расширения.
  const добавить = page.getByRole('button', { name: t('diagrams.work.addFile') }).first()
  for (const имя of ['первый.py', 'второй.py']) {
    await добавить.click()
    const окно_файла = page.getByRole('dialog')
    await окно_файла.getByLabel(t('diagrams.work.fileName')).fill(имя)
    await окно_файла.getByRole('button', { name: t('diagrams.work.addFile') }).click()
    // Именно кнопка списка: имя стоит и в шапке поля кода у выбранного файла.
    await expect(page.getByRole('button', { name: имя, exact: true })).toBeVisible()
  }
  // Код есть — строить уже есть чем.
  const кодUml = page.getByRole('textbox', { name: t('diagrams.work.codeLabel') })
  await кодUml.click()
  await page.keyboard.insertText('class A:\n    pass\n')
  await expect(page.getByText(t('diagrams.work.buildNeedsCode'))).toHaveCount(0)

  // Убирается любой файл, и последний тоже: тогда строить снова нечего.
  for (const имя of ['второй.py', 'первый.py']) {
    await page
      .getByRole('button', { name: t('diagrams.work.removeFileNamed', { name: имя }) })
      .click()
    await expect(page.getByText(имя)).toHaveCount(0)
  }
  await expect(page.getByText(t('diagrams.work.noFiles'))).toBeVisible()
  await expect(page.getByText(t('diagrams.work.buildNeedsCode'))).toBeVisible()
  await expect(построить).toBeDisabled()

  // ── 5. схема видна в списке модуля и в журнале работы ─────────────────────
  await page.goto('/flowcharts')
  const строка = page.getByRole('listitem').filter({ hasText: имяСхемы('flowcharts', 1) })
  await expect(строка).toHaveCount(1)

  await page.goto(`/projects/${projectId}`)
  await expect(page.getByText(имяСхемы('flowcharts', 1))).toBeVisible()

  // ── 5а. переименование в списке модуля ────────────────────────────────────
  const НОВОЕ = 'Алгоритм сортировки'
  await page.goto('/flowcharts')
  await page
    .getByRole('button', { name: t('projects.runs.rename', { name: имяСхемы('flowcharts', 1) }) })
    .click()
  await page.keyboard.type(НОВОЕ)
  await page.keyboard.press('Enter')
  await expect(page.getByText(НОВОЕ)).toBeVisible()
  await expect(page.getByText(имяСхемы('flowcharts', 1))).toHaveCount(0)

  // Имя одно на весь сайт: журнал работы показывает его же.
  await page.goto(`/projects/${projectId}`)
  await expect(page.getByText(НОВОЕ)).toBeVisible()

  // ── 5б. переименование на экране схемы, и `Esc` ничего не меняет ──────────
  await page.goto('/flowcharts')
  await page
    .getByRole('listitem')
    .filter({ hasText: НОВОЕ })
    .getByRole('button', { name: t('diagrams.home.open') })
    .click()
  await expect(page).toHaveURL(/\/flowcharts\/[0-9a-f-]{36}\?run=/)
  await expect(page.getByText(НОВОЕ)).toBeVisible({ timeout: 60_000 })

  await page.getByRole('button', { name: t('projects.runs.rename', { name: НОВОЕ }) }).click()
  await page.keyboard.type('передумал')
  await page.keyboard.press('Escape')
  await expect(page.getByText(НОВОЕ)).toBeVisible()

  const ВТОРОЕ = 'Схема алгоритма'
  await page.getByRole('button', { name: t('projects.runs.rename', { name: НОВОЕ }) }).click()
  await page.keyboard.type(ВТОРОЕ)
  await page.keyboard.press('Enter')
  await expect(page.getByText(ВТОРОЕ)).toBeVisible()

  await page.goto(`/projects/${projectId}`)
  await expect(page.getByText(ВТОРОЕ)).toBeVisible()

  // Пустое имя — не отказ, а возврат к имени по умолчанию.
  await page.goto('/flowcharts')
  await page.getByRole('button', { name: t('projects.runs.rename', { name: ВТОРОЕ }) }).click()
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Delete')
  await page.keyboard.press('Enter')
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
