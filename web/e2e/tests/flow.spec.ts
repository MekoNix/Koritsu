/**
 * Путь человека целиком: регистрация → почта → вход → проект с шаблоном →
 * материал → отчёт → прогон модели по потоку → превью PDF → версии и откат →
 * блок-схема → настройки → выход.
 *
 * Одна проверка, а не двадцать, и намеренно: это один путь, каждый шаг которого
 * держится на предыдущем. Разбить его на независимые проверки означало бы
 * двадцать раз завести человека, проект и шаблон — то есть проверять заведение
 * проекта двадцать раз и путь человека ни разу.
 *
 * Правила устойчивости, которых держимся:
 *
 * * тексты — ключами перевода (`helpers.t`), а не строками: правка слова в
 *   словаре не должна ронять проверку;
 * * ожидание — `expect`/`expect.poll`, ни одного `waitForTimeout`: сон на две
 *   секунды либо лишний, либо однажды окажется коротким;
 * * поиск — по ролям и подписям, а не по классам Tailwind: классы меняются
 *   вместе с видом, роли — вместе со смыслом.
 */
import { expect, test } from '@playwright/test'

import { PASSWORD, TAG_ONE, TAG_TWO, signUpAndLogin, t, templateDocx } from './helpers'

const ПРОЕКТ = 'Сквозная проверка сайта'

test('путь человека: от регистрации до выхода', async ({ page }) => {
  // ── 1. регистрация, подтверждение почты, вход ─────────────────────────────
  const email = await signUpAndLogin(page, 'flow')
  await expect(page).toHaveURL(/\/$/)

  // ── 2. проект с шаблоном DOCX ─────────────────────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await expect(page.getByRole('heading', { name: t('projects.list.title') })).toBeVisible()

  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('projects.create.name')).fill(ПРОЕКТ)
  await окно.locator('input[type="file"]').setInputFiles(templateDocx())
  await expect(окно.getByText('шаблон-проверки.docx')).toBeVisible()
  await окно.getByRole('button', { name: t('common.action.create') }).click()

  // Создание уводит на карточку проекта; адрес — с идентификатором.
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('heading', { name: ПРОЕКТ })).toBeVisible()
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // Теги шаблона распознались службой — это видно в подзаголовке карточки.
  await expect(page.getByText(t('projects.page.tags', { n: 2 }))).toBeVisible()

  // ── 3. материал: загрузка, разбор, карточка ───────────────────────────────
  await page
    .locator('input[type="file"]')
    .first()
    .setInputFiles({
      name: 'условие.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Условие задачи: разобрать сортировку пузырьком.', 'utf8'),
    })

  // Разбор идёт заданием: строка «разбирается» сменяется карточкой файла.
  const карточка = page.getByRole('listitem').filter({ hasText: 'условие.txt' })
  await expect(карточка.getByRole('button', { name: t('projects.materials.preview') })).toBeVisible(
    { timeout: 60_000 },
  )
  await карточка.getByRole('button', { name: t('projects.materials.preview') }).click()
  await expect(карточка.getByText(/сортировку пузырьком/)).toBeVisible()

  // ── 4. отчёт: тег, прогон модели, текст по потоку ─────────────────────────
  // Через главную модуля, как ходит человек: сайдбар → плитка работы.
  await page
    .locator('aside')
    .getByRole('link', { name: t('shell.nav.reports') })
    .click()
  await expect(page.getByRole('heading', { name: t('reports.home.title') })).toBeVisible()
  await page.getByRole('link', { name: ПРОЕКТ }).click()
  // Главная отчётов в два шага: сначала работа, потом её отчёты. Отчётов в
  // работе бывает несколько, и первый из них заводится здесь же — он забирает
  // собственный документ работы вместе с её бланком и тегами.
  await expect(page).toHaveURL(new RegExp(`/reports\\?project=${projectId}$`))
  await page
    .getByRole('button', { name: t('reports.list.create') })
    .first()
    .click()
  const окно_отчёта = page.getByRole('dialog')
  await окно_отчёта.getByLabel(t('reports.list.nameLabel')).fill('Отчёт по работе')
  await окно_отчёта.getByRole('button', { name: t('reports.list.createAction') }).click()
  await expect(page).toHaveURL(new RegExp(`/reports/${projectId}/[0-9a-f-]{36}`), {
    timeout: 30_000,
  })

  // Теги пришли из шаблона: оба, и оба пустые.
  await expect(page.getByRole('button', { name: new RegExp(TAG_ONE) })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText(t('reports.tags.counter', { filled: 0, total: 2 }))).toBeVisible()

  const поле = page.getByRole('textbox', { name: t('reports.editor.field', { tag: TAG_ONE }) })
  await expect(поле).toBeVisible()
  await expect(поле).toHaveValue('')

  // `exact`: рядом стоит «Сгенерировать всё», и подпись одной кнопки —
  // начало подписи другой.
  await page.getByRole('button', { name: t('reports.editor.generate'), exact: true }).click()
  // Текст приходит кусками по SSE и оказывается прямо в поле: ждём не «поле
  // не пустое», а тот след поддельной модели, который она кладёт в ответ.
  await expect(поле).toHaveValue(/поддельн/, { timeout: 90_000 })
  // Конец задания: тег помечен как написанный моделью.
  await expect(page.getByText(t('reports.tags.byAgent', { n: 1 }))).toBeVisible({ timeout: 60_000 })

  // ── 5. «сгенерировать всё» — второй тег ───────────────────────────────────
  await page.getByRole('button', { name: t('reports.work.fillAll') }).click()
  const всё = page.getByRole('dialog')
  await expect(всё.getByText(t('reports.fillAll.keepsManual'))).toBeVisible()
  // Прогон идёт только по пустым: заполненного «цель» в списке окна нет.
  await expect(всё.getByText(`{{${TAG_TWO}}}`)).toBeVisible()
  await expect(всё.getByText(`{{${TAG_ONE}}}`)).toHaveCount(0)
  await всё.getByRole('button', { name: t('reports.fillAll.start') }).click()

  await expect(page.getByText(t('reports.tags.counter', { filled: 2, total: 2 }))).toBeVisible({
    timeout: 120_000,
  })

  // ── 6. превью PDF ─────────────────────────────────────────────────────────
  await page
    .getByRole('button', { name: t('reports.pdf.build'), exact: true })
    .first()
    .click()
  const превью = page.locator('embed[type="application/pdf"]')
  await expect(превью).toBeVisible({ timeout: 120_000 })
  // Показывается прямой адрес артефакта с `?inline=1`: служба по этому
  // параметру отдаёт PDF с `Content-Disposition: inline`, и просмотрщик рисует
  // его на месте. Без параметра заголовок был бы `attachment`, и браузер
  // скачал бы файл вместо того, чтобы показать, — поэтому проверяется именно
  // адрес, а не только видимость `<embed>`.
  await expect(превью).toHaveAttribute('src', /\/api\/projects\/.+\/artifacts\/.+\?inline=1$/)
  // Копии в памяти вкладки больше нет: `blob:` был обходом, а не задумкой.
  await expect(превью).not.toHaveAttribute('src', /^blob:/)
  // Скачивание при этом осталось скачиванием: ссылка ведёт на тот же адрес БЕЗ
  // параметра, и по ней приезжает файл.
  const скачать_pdf = page.getByRole('link', { name: t('reports.pdf.downloadPdf') })
  await expect(скачать_pdf).toHaveAttribute('href', /\/api\/projects\/.+\/artifacts\/[^?]+$/)
  const [собранный] = await Promise.all([page.waitForEvent('download'), скачать_pdf.click()])
  expect(await собранный.failure()).toBeNull()
  expect(собранный.suggestedFilename()).toMatch(/\.pdf$/)
  await expect(page.getByRole('link', { name: t('reports.pdf.downloadDocx') })).toBeVisible()

  // ── 7. версии тега и откат ────────────────────────────────────────────────
  await page.getByRole('button', { name: new RegExp(TAG_ONE) }).click()
  const своё = 'Написано рукой на сквозной проверке.'
  await поле.fill(своё)
  await page.getByRole('button', { name: t('common.action.save'), exact: true }).click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 2 }))).toBeVisible()

  await page.getByRole('button', { name: t('reports.versions.title') }).click()
  const версии = page.getByRole('listitem').filter({ hasText: 'v1' })
  await версии.getByRole('button', { name: t('reports.versions.rollback') }).click()
  // Возврат спрашивают: он переписывает то, что человек видит на экране.
  await page
    .getByRole('dialog', { name: t('reports.versions.rollbackTitle', { n: 1 }) })
    .getByRole('button', { name: t('reports.versions.rollback') })
    .click()
  // Возврат — это новая версия с прежним текстом, а не удаление второй.
  await expect(поле).toHaveValue(/поддельн/)
  await expect(page.getByText(t('reports.editor.byAgent', { n: 3 }))).toBeVisible()

  // ── 8. блок-схема ─────────────────────────────────────────────────────────
  await page.goto(`/flowcharts/${projectId}`)
  await expect(
    page.getByRole('heading', { name: t('diagrams.home.flowcharts.title') }),
  ).toBeVisible()

  const код = page.getByRole('textbox', { name: t('diagrams.work.codeLabel') })
  await код.click()
  await page.keyboard.insertText('def main():\n    x = 1\n    if x:\n        print(x)\n')
  await page.getByRole('button', { name: t('diagrams.work.build') }).click()

  // Кнопка «скачать XML» оживает только тогда, когда служба вернула схему.
  const xml = page.getByRole('button', { name: t('diagrams.work.downloadXml') })
  await expect(xml).toBeEnabled({ timeout: 60_000 })

  // Кадр draw.io живёт на чужом домене. Есть сеть — он отзовётся и скажет об
  // этом строкой в шапке; нет — экран обязан показать «предпросмотр недоступен»
  // и не сломаться. Проверяем, что случилось одно из двух, а не что-то третье.
  const редактор = page.getByText(t('diagrams.preview.editorHint'))
  const недоступен = page.getByText(t('diagrams.preview.offline'))
  await expect
    .poll(
      async () =>
        (await редактор.count()) ? 'ready' : (await недоступен.count()) ? 'offline' : '',
      { timeout: 60_000 },
    )
    .not.toBe('')

  const скачивание = page.waitForEvent('download')
  await xml.click()
  const файл = await скачивание
  expect(файл.suggestedFilename()).toMatch(/\.drawio\.xml$/)

  // Кнопки «сохранить в проект» нет: построенная схема уже в работе, под своим
  // именем из журнала запусков.
  const имяСхемы = t('projects.runs.autoName', {
    unit: t('projects.runs.unit.flowcharts'),
    n: 1,
    project: ПРОЕКТ,
  })
  await expect(page.getByText(t('diagrams.work.savedAs'))).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(имяСхемы)).toBeVisible()

  // ── 9. настройки: ключ модели, ключ для скриптов, тема ────────────────────
  // Ключи поставщиков живут в «Конфигурации агентов»: пресет и ключ, которым за
  // него платят, выбираются вместе. Прежний адрес `/settings/keys` на неё
  // перенаправляет, но проверка ходит по нынешнему.
  await page.goto('/settings/agent')
  await page.getByLabel(t('settings.keys.provider')).selectOption('deepseek')
  // `exact` обязателен: на этом экране рядом с полем «Ключ» стоит переключатель
  // «Переписывать ручные правки», и подпись его состояния («Выключено») тоже
  // содержит эти буквы — неточный поиск нашёл бы два элемента.
  await page.getByLabel(t('settings.keys.value'), { exact: true }).fill('sk-e2e-check-1234')
  await page.getByRole('button', { name: t('settings.keys.add') }).click()
  // Служба отдаёт только последние четыре знака — по ним и узнаём ключ.
  await expect(page.getByText('…1234')).toBeVisible({ timeout: 30_000 })
  // …и с этого мгновения `deepseek` платится своим ключом, а не общим.
  await expect(page.getByText(t('settings.keys.source.own'), { exact: true })).toBeVisible()

  await page.goto('/settings/tokens')
  await page
    .getByRole('button', { name: t('settings.tokens.create') })
    .first()
    .click()
  const ключ = page.getByRole('dialog')
  await ключ.getByLabel(t('settings.tokens.name')).fill('Проверка')
  await ключ.getByRole('checkbox').first().check()
  await ключ.getByRole('button', { name: t('settings.tokens.create') }).click()

  // Строка ключа показывается один раз — окном, из которого её и копируют.
  const показ = page.getByRole('dialog')
  await expect(показ.getByText(t('settings.tokens.onceTitle'))).toBeVisible()
  const строка = (await показ.locator('code').innerText()).trim()
  expect(строка).toMatch(/^kor_/)
  await показ.getByRole('button', { name: t('common.action.close'), exact: true }).click()
  // Второй раз её не покажут никому: в списке остаётся только приставка.
  await expect(page.getByText(строка)).toHaveCount(0)

  await page.goto('/settings/appearance')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate')

  // Тема — «Бумага»; вместе с ней встаёт её родной светлый вариант.
  const темы = page.getByRole('radiogroup', { name: t('settings.appearance.theme') })
  await темы.getByRole('radio').filter({ hasText: 'Бумага' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'paper')

  // Вариант выбирается отдельным переключателем: «Тёмная» поверх светлой темы.
  const варианты = page.getByRole('radiogroup', { name: t('settings.appearance.mode') })
  await варианты.getByRole('radio', { name: t('settings.appearance.modeDark') }).click()
  await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')

  await page.reload()
  // Выбор переживает перезагрузку: его применяет встроенный скрипт `index.html`
  // до первого рендера, иначе страница мигала бы чужими цветами.
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'paper')
  await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')

  // ── 10. админка: без права — отказ ────────────────────────────────────────
  await page.goto('/admin')
  await expect(page.getByText(t('common.state.forbidden'))).toBeVisible()

  // ── 11. выход ─────────────────────────────────────────────────────────────
  await page.goto('/')
  await page.getByRole('button', { name: t('shell.user.menu') }).click()
  await page.getByRole('menuitem', { name: t('shell.user.logout') }).click()
  await expect(page).toHaveURL(/\/auth\/login$/)

  // Вошедшего больше нет: закрытый адрес уводит обратно на вход.
  await page.goto(`/projects/${projectId}`)
  await expect(page).toHaveURL(/\/auth\/login$/)
  // …и почта с паролем при этом настоящие — вход тем же человеком проходит.
  await page.getByLabel(t('auth.field.email')).fill(email)
  await page.getByLabel(t('auth.field.password'), { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: t('auth.login.submit') }).click()
  await expect(page.getByRole('heading', { name: ПРОЕКТ })).toBeVisible()
})
