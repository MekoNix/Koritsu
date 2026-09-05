/**
 * Правила брифа, проверенные машиной, а не глазами.
 *
 * Три из них ломаются молча: полоску у активного пункта возвращает одна строка
 * Tailwind, раскрытие меню по наведению — один `hover:` в классе, а лишний
 * пункт в сайдбаре появляется сам, стоит только перестать спрашивать службу.
 * Поэтому они здесь, а не в списке того, что «надо посмотреть».
 *
 *   1. у активного пункта сайдбара нет цветной полоски слева;
 *   2. сайдбар сворачивается кнопкой, а не наведением;
 *   3. модуль, которого нет в `GET /api/modules`, в меню не показан.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'

/** Слева ли у элемента цветная полоска — рамкой, обводкой, тенью, псевдоэлементом. */
async function полоскаСлева(page: Page, селектор: string): Promise<{ [k: string]: string }> {
  return page
    .locator(селектор)
    .first()
    .evaluate((el) => {
      const свой = getComputedStyle(el)
      const до = getComputedStyle(el, '::before')
      const после = getComputedStyle(el, '::after')
      const ширина = (s: CSSStyleDeclaration) => (s.content === 'none' ? '0px' : s.width)
      return {
        borderLeftStyle: свой.borderLeftStyle,
        borderLeftWidth: свой.borderLeftWidth,
        // `outline-width` бывает ненулевым и при `outline-style: none` — это
        // заготовка правила фокуса, а не полоска. Смотрим оба поля.
        outlineStyle: свой.outlineStyle,
        outlineWidth: свой.outlineWidth,
        boxShadow: свой.boxShadow,
        beforeContent: до.content,
        beforeWidth: ширина(до),
        afterContent: после.content,
        afterWidth: ширина(после),
      }
    })
}

/**
 * Ширина сайдбара, когда она перестала меняться.
 *
 * Меню меняет ширину переходом (`transition-[width] duration-200`), и
 * измерение сразу после нажатия ловит середину движения — число, которое
 * больше никогда не повторится. Поэтому ждём двух одинаковых замеров подряд.
 */
async function устоявшаясяШирина(меню: Locator): Promise<number> {
  const замер = () => меню.evaluate((el) => el.getBoundingClientRect().width)
  let прошлая = Number.NaN
  await expect
    .poll(
      async () => {
        const сейчас = await замер()
        const устоялась = сейчас === прошлая
        прошлая = сейчас
        return устоялась
      },
      { timeout: 10_000 },
    )
    .toBe(true)
  return прошлая
}

test.describe('правила брифа', () => {
  test.beforeEach(async ({ page }) => {
    await signUpAndLogin(page, 'brief')
  })

  test('у активного пункта сайдбара нет цветной полоски слева', async ({ page }) => {
    const активный = 'aside a[aria-current="page"]'
    await expect(page.locator(активный)).toHaveCount(1)

    const стиль = await полоскаСлева(page, активный)
    // Полоска в CSS выражается четырьмя способами, и все четыре запрещены.
    expect(стиль.borderLeftStyle === 'none' || стиль.borderLeftWidth === '0px').toBe(true)
    expect(стиль.outlineStyle === 'none' || стиль.outlineWidth === '0px').toBe(true)
    expect(стиль.boxShadow === 'none' || стиль.boxShadow === '').toBe(true)
    expect(стиль.beforeContent === 'none' || стиль.beforeWidth === '0px').toBe(true)
    expect(стиль.afterContent === 'none' || стиль.afterWidth === '0px').toBe(true)

    // Активность всё-таки видна — заливкой: пункт не должен быть неотличим.
    const фон = await page.locator(активный).evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(фон).not.toBe('rgba(0, 0, 0, 0)')
  })

  test('сайдбар сворачивается кнопкой, а не наведением', async ({ page }) => {
    const меню = page.locator('aside').first()
    const развёрнутый = await устоявшаясяШирина(меню)

    // Свернуть кнопкой.
    await page.getByRole('button', { name: t('shell.sidebar.collapse') }).click()
    await expect(page.getByRole('button', { name: t('shell.sidebar.expand') })).toBeVisible()
    const свёрнутый = await устоявшаясяШирина(меню)
    expect(свёрнутый).toBeLessThan(развёрнутый)

    // Навести курсор — и убедиться, что ничего не произошло: ни ширина, ни
    // подписи. `hover` наводится на само меню и на пункт внутри него.
    await меню.hover()
    await page.locator('aside a').first().hover()
    expect(await устоявшаясяШирина(меню)).toBe(свёрнутый)
    await expect(page.getByRole('button', { name: t('shell.sidebar.expand') })).toBeVisible()

    // Развернуть — снова кнопкой.
    await page.getByRole('button', { name: t('shell.sidebar.expand') }).click()
    expect(await устоявшаясяШирина(меню)).toBe(развёрнутый)
  })

  test('модуль, которого нет в /api/modules, в сайдбаре не показан', async ({ page }) => {
    // Служба отдаёт три модуля; подменяем ответ так, чтобы `uml` из него исчез,
    // а вместо него появился модуль, которого сайт не знает вовсе.
    await page.route('**/api/modules', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'reports', title: 'Reports', routes: '/api/projects' },
          { id: 'flowcharts', title: 'Flowcharts', routes: '/api/flowcharts' },
          { id: 'assembler', title: 'Assembler', routes: '/api/assembler' },
        ]),
      })
    })
    await page.reload()

    const меню = page.locator('aside')
    await expect(меню.getByRole('link', { name: t('shell.nav.reports') })).toBeVisible()
    await expect(меню.getByRole('link', { name: t('shell.nav.flowcharts') })).toBeVisible()
    // Модуль, которого служба не отдала, — не показан.
    await expect(меню.getByRole('link', { name: t('shell.nav.uml') })).toHaveCount(0)
    // Модуль, которому на сайте нет страницы, — тоже: ссылка в никуда хуже её
    // отсутствия (`app/shell/moduleLinks.ts`).
    await expect(меню.getByRole('link', { name: /assembler/i })).toHaveCount(0)
  })

  test('в сайдбаре есть «Задания» и нет модулей из макета, которых у службы нет', async ({
    page,
  }) => {
    const меню = page.locator('aside')

    // Модуль ночи 2: служба его отдаёт (`GET /api/modules`), страница есть.
    await expect(меню.getByRole('link', { name: t('shell.nav.kadai'), exact: true })).toBeVisible()

    // А эти три нарисованы в макетах, но модулями службы не являются. Строкой,
    // а не ключом перевода: ключа у них нет и быть не должно — проверяется
    // именно то, что слова не завелись (§2 брифа: неготовых пунктов нет).
    for (const слово of [/карточк/i, /доск/i, /ассемблер/i]) {
      await expect(меню.getByRole('link', { name: слово })).toHaveCount(0)
    }
  })
})
