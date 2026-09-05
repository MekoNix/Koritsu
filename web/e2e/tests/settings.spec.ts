/**
 * Настройки с API: шаблоны отчётов, горячие клавиши, умолчания агента.
 *
 * Проверяется то, что нельзя проверить ни `tests/api`, ни vitest: путь целиком
 * — от загрузки DOCX в настройках до тегов в работе, заведённой по этому
 * шаблону. Между ними лежит всё, что бывает сломано по отдельности: multipart
 * с cookie и CSRF из браузера, разбор манифеста службой, копия байтов в проект.
 *
 * Три проверки, по одной на раздел:
 *
 * 1. **Шаблон.** Загрузили → он в списке с числом тегов → завели по нему
 *    работу → в работе те же теги. Число тегов сверяется в двух местах
 *    намеренно: разойтись они могут только молча.
 * 2. **Горячие клавиши.** Переназначили сочетание панели агента — подсказка на
 *    кнопке поменялась, и панель открывается новым сочетанием. Без второй
 *    половины проверка доказывала бы только то, что подпись перерисовалась.
 * 3. **Агент и модели.** Включили «переписывать ручные правки» — панель агента
 *    открывается с включённой галкой, а не с выключенной по умолчанию. Пресет
 *    проверяется тем, что выбор переживает перезагрузку страницы: он лежит в
 *    профиле, а не в браузере.
 */
import { expect, test } from '@playwright/test'

import { TAG_ONE, TAG_TWO, signUpAndLogin, t, templateDocx } from './helpers'

test.describe('настройки с API', () => {
  test('шаблон из настроек становится тегами работы', async ({ page }) => {
    await signUpAndLogin(page, 'templates')

    await page.goto('/settings/templates')
    await expect(page.getByText(t('settings.templates.empty'))).toBeVisible()

    await page.getByLabel(t('settings.templates.drop')).setInputFiles(templateDocx())
    await page.getByLabel(t('settings.templates.name')).fill('ГОСТ 2026')
    await page.getByRole('button', { name: t('settings.templates.add') }).click()

    // Тегов в шаблоне два — столько же обязано оказаться в работе по нему.
    await expect(page.getByText('ГОСТ 2026')).toBeVisible()
    await expect(page.getByText(t('settings.templates.tags', { count: 2 }))).toBeVisible()

    await page.goto('/projects')
    await page
      .getByRole('button', { name: t('projects.list.create') })
      .first()
      .click()
    await page.getByLabel(t('projects.create.name')).fill('Работа по своему шаблону')
    // Вторым пунктом (первый — «Не выбран»): в подписи пункта рядом с именем
    // стоит число тегов, и точной строкой её не назвать.
    await page.getByLabel(t('projects.create.templateSaved')).selectOption({ index: 1 })
    await page.getByRole('button', { name: t('common.action.create') }).click()

    // Карточка работы считает теги шаблона — их столько же, сколько в списке
    // шаблонов. Это и есть то, что расходится молча, если считать их дважды.
    await expect(page.getByText(t('projects.page.tags', { n: 2 }), { exact: false })).toBeVisible()

    // А сами теги видно на экране отчёта — по ним и заполняют работу. Идём
    // адресом, а не ссылкой: слово «Отчёты» на странице есть дважды — в
    // сайдбаре и в списке модулей работы.
    const id = new URL(page.url()).pathname.split('/').pop()
    await page.goto(`/reports/${id}`)
    await expect(page.getByText(TAG_ONE, { exact: false }).first()).toBeVisible()
    await expect(page.getByText(TAG_TWO, { exact: false }).first()).toBeVisible()
  })

  test('переназначенное сочетание открывает панель агента', async ({ page }) => {
    await signUpAndLogin(page, 'hotkeys')

    await page.goto('/settings/hotkeys')
    const строка = page.locator('li', { hasText: t('settings.hotkeys.action.agent') })
    await строка.getByRole('button', { name: t('settings.hotkeys.change') }).click()

    // Записываем Ctrl+Shift+G: три обычных сочетания сайта им не заняты.
    await page.keyboard.press('Control+Shift+G')
    await expect(page.getByText('Ctrl Shift G')).toBeVisible()
    await page.getByRole('button', { name: t('common.action.save') }).click()

    // Подсказка на кнопке в шапке — то же самое сочетание.
    await expect(page.getByRole('button', { name: /Ctrl Shift G/ })).toBeVisible()

    // И оно правда открывает панель, а не только нарисовано.
    await page.keyboard.press('Control+Shift+G')
    await expect(page.getByRole('dialog', { name: t('agent.title') })).toBeVisible()
  })

  test('умолчания агента живут в профиле и приезжают в панель', async ({ page }) => {
    await signUpAndLogin(page, 'agentdef')

    await page.goto('/settings/agent')
    await page.getByLabel(t('settings.agent.preset')).selectOption('deepseek')
    await page.getByRole('switch').check()

    // Перезагрузка страницы — то самое, что отличает профиль от `localStorage`.
    await page.reload()
    await expect(page.getByLabel(t('settings.agent.preset'))).toHaveValue('deepseek')
    await expect(page.getByRole('switch')).toBeChecked()

    // Панель агента открывается с тем, что человек выбрал: галка включена
    // (умолчание сайта — выключена), пресет — выбранный.
    await page.goto('/projects')
    await page.getByRole('button', { name: /Ctrl J/ }).click()
    const панель = page.getByRole('dialog', { name: t('agent.title') })
    await expect(панель).toBeVisible()
    await expect(панель.getByRole('checkbox', { name: t('agent.overwrite') })).toBeChecked()
    await expect(панель.getByLabel(t('reports.model.label'))).toHaveValue('deepseek')
  })
})
