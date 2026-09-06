/**
 * Админка: её видит только тот, у кого право есть.
 *
 * Право выдаётся тем же способом, каким его выдают на боевой машине, —
 * строкой в базе (`UPDATE users SET is_admin=1`). Ручки «сделай меня админом» у
 * службы нет и заводить её нельзя: она и была бы дырой, ради закрытия которой
 * весь `/api/admin` закрыт `require_admin`.
 *
 * Проверяется ровно то, что нельзя проверить ни в службе, ни в vitest: сайт
 * узнаёт право из `is_admin` в `GET /api/auth/me` и показывает `/admin`. В
 * сайдбаре пункта админки нет ни у кого — попасть в неё можно ссылкой из меню
 * пользователя (она есть только у владельца службы) или прямым адресом.
 */
import { execFileSync } from 'node:child_process'

import { expect, test } from '@playwright/test'

import {
  PASSWORD,
  TAG_ONE,
  login as войти,
  logout as выйти,
  nicknameFor,
  signUpAndLogin,
  t,
  templateDocx,
  uniqueEmail,
} from './helpers'
import { DB_FILE, PYTHON } from './stand'

/** Выдать право администратора прямо в базе тома. */
function сделатьАдмином(email: string): void {
  execFileSync(
    PYTHON,
    [
      '-c',
      [
        'import sqlite3, sys',
        'связь = sqlite3.connect(sys.argv[1])',
        'курсор = связь.execute("UPDATE users SET is_admin=1 WHERE email=?", (sys.argv[2],))',
        'связь.commit()',
        'assert курсор.rowcount == 1, f"строк изменено: {курсор.rowcount}"',
      ].join('\n'),
      DB_FILE,
      email,
    ],
    { stdio: 'pipe' },
  )
}

test('право администратора открывает /admin и в сайдбар не выводится', async ({ page }) => {
  const email = await signUpAndLogin(page, 'admin')

  // Пока права нет — честный отказ, а не пустой экран и не «не найдено».
  await page.goto('/admin')
  await expect(page.getByText(t('common.state.forbidden'))).toBeVisible()

  сделатьАдмином(email)

  // Перезагрузка перечитывает профиль: право приезжает полем `is_admin`.
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: t('admin.title') })).toBeVisible()
  await expect(page.getByRole('link', { name: t('admin.tab.queue') })).toBeVisible()

  // Вкладка — часть адреса, а не состояние страницы.
  await page.getByRole('link', { name: t('admin.tab.queue') }).click()
  await expect(page).toHaveURL(/\/admin\/queue$/)
  await expect(page.getByRole('heading', { name: t('admin.queue.title') })).toBeVisible()

  // Люди: свой человек в списке есть.
  await page.getByRole('link', { name: t('admin.tab.users') }).click()
  await expect(page.getByText(email)).toBeVisible()

  // И главное: пункта админки в сайдбаре нет ни у кого — она вынесена на своё
  // имя, и в списке модулей ей не место.
  await page.goto('/')
  await expect(page.locator('aside').getByRole('link', { name: t('shell.nav.admin') })).toHaveCount(
    0,
  )
  await expect(page.locator('a[href="/admin"]')).toHaveCount(0)
})

/**
 * Обзор админки: три графика с данными.
 *
 * Данные заводятся тем же путём, каким они появляются у администратора, —
 * работой и прогоном: регистрация даёт точку в ряду регистраций, прогон
 * модели — расход
 * за сутки и строку в разбивке по видам. Подкладывать числа в базу здесь
 * нельзя: проверяется, что сайт показывает то, что служба посчитала, а не то,
 * что проверка ей подложила.
 */
test('обзор админки: расход, виды заданий и регистрации нарисованы с данными', async ({ page }) => {
  test.setTimeout(180_000)
  const email = await signUpAndLogin(page, 'overview')

  // ── работа и один прогон: иначе рисовать нечего ───────────────────────────
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const создание = page.getByRole('dialog')
  await создание.getByLabel(t('projects.create.name')).fill('Работа для обзора')
  await создание.locator('input[type="file"]').setInputFiles(templateDocx())
  await создание.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  await page.goto(`/reports/${projectId}`)
  const поле = page.getByRole('textbox', { name: t('reports.editor.field', { tag: TAG_ONE }) })
  await expect(поле).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: t('reports.editor.generate'), exact: true }).click()
  await expect(page.getByText(t('reports.tags.byAgent', { n: 1 }))).toBeVisible({ timeout: 90_000 })

  сделатьАдмином(email)

  // ── обзор ─────────────────────────────────────────────────────────────────
  await page.goto('/admin')
  // Голый `/admin` — это обзор: вкладка названа адресом, а не состоянием
  // страницы.
  await expect(page).toHaveURL(/\/admin\/overview$/)
  await expect(page.getByRole('heading', { name: t('admin.overview.usage') })).toBeVisible({
    timeout: 30_000,
  })
  // Данные есть — значит пустых состояний нет ни у сводки, ни у видов.
  await expect(page.getByText(t('admin.overview.empty'))).toHaveCount(0)
  await expect(page.getByText(t('admin.overview.noJobs'))).toHaveCount(0)

  // Три графика, каждый — картинка со своим именем: это единственное, чем один
  // рисованный svg отличается от соседнего для того, кто смотрит не глазами.
  for (const ключ of ['usage', 'kinds', 'registrations']) {
    await expect(page.getByRole('img', { name: t(`admin.overview.${ключ}`) })).toBeVisible()
  }

  /** Таблица графика для скринридера: те же числа, только текстом. */
  const таблица = (подпись: string) =>
    page.locator('table').filter({ has: page.locator('caption', { hasText: подпись }) })

  // Ряд расхода — по строке на каждый день периода (умолчание — 30), и хотя бы
  // в одном дне число не нулевое: прогон только что был.
  const расход = таблица(t('admin.overview.usage'))
  await expect(расход.locator('tbody tr')).toHaveCount(30)
  const списано = await расход.locator('tbody tr td:nth-child(2)').allInnerTexts()
  expect(списано.some((число) => /[1-9]/.test(число))).toBe(true)

  // Разбивка по видам: прогон, который мы только что заказали, в ней есть.
  const виды = таблица(t('admin.overview.kinds'))
  await expect(виды.locator('tbody tr').filter({ hasText: 'fill_tag' })).toHaveCount(1)

  // Регистрации: свой человек заведён сегодня, значит день не пустой.
  const регистрации = таблица(t('admin.overview.registrations'))
  const заведено = await регистрации.locator('tbody tr td:nth-child(2)').allInnerTexts()
  expect(заведено.some((число) => /[1-9]/.test(число))).toBe(true)

  // Период — переключателем, и ряд перерисовывается под него.
  await page
    .getByRole('radiogroup', { name: t('admin.overview.period') })
    .getByRole('radio', { name: t('admin.overview.days', { n: 7 }) })
    .click()
  await expect(таблица(t('admin.overview.usage')).locator('tbody tr')).toHaveCount(7)
})

/**
 * Блокировка: администратор закрывает вход, и человек не входит, пока его не
 * откроют обратно.
 *
 * Проверяется склейка трёх мест, каждое из которых по отдельности выглядит
 * правильным: кнопка в карточке (`PATCH
 * /api/admin/users/{id}` с `blocked`), отказ на входе (`403 account_blocked`)
 * и снятие блокировки. Главного не видит ни служба, ни vitest: заблокированный
 * получает на экране входа СВОЙ текст по коду, а не «неверная почта или
 * пароль», — иначе он пойдёт менять пароль вместо того, чтобы написать
 * администратору.
 */
test('блокировка: вход отказан, разблокировка возвращает его', async ({ page }) => {
  test.setTimeout(180_000)

  // Жертву заводим первой: блокировать можно только заведённого.
  const жертва = await signUpAndLogin(page, 'blocked')
  await выйти(page)

  const админ = await signUpAndLogin(page, 'blocker')
  сделатьАдмином(админ)

  /** Открыть карточку человека по почте: строка таблицы — кнопка. */
  async function открыть(почта: string) {
    await page.goto('/admin/users')
    await page.getByLabel(t('admin.users.search')).fill(почта)
    const строка = page.getByRole('button').filter({ hasText: почта })
    await expect(строка).toBeVisible({ timeout: 30_000 })
    await строка.click()
    const карточка = page.getByRole('dialog', { name: t('admin.card.title') })
    await expect(карточка).toBeVisible()
    return карточка
  }

  // ── заблокировать ─────────────────────────────────────────────────────────
  let карточка = await открыть(жертва)
  await карточка.getByRole('button', { name: t('admin.card.block') }).click()
  const вопрос = page.getByRole('dialog', { name: t('admin.card.blockTitle') })
  await expect(вопрос).toBeVisible()
  await вопрос.getByRole('button', { name: t('admin.card.block') }).click()

  // Состояние человека в списке — «заблокирован», а не «активен».
  await page.goto('/admin/users')
  await page.getByLabel(t('admin.users.search')).fill(жертва)
  await expect(page.getByRole('button').filter({ hasText: жертва })).toContainText(
    t('admin.users.status.blocked'),
    { timeout: 30_000 },
  )

  // ── вход отказан, и отказ говорит правду ──────────────────────────────────
  await выйти(page)
  await page.goto('/auth/login')
  await page.getByLabel(t('auth.field.email')).fill(жертва)
  await page.getByLabel(t('auth.field.password'), { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: t('auth.login.submit') }).click()
  await expect(page.getByText(t('errors.account_blocked.what'))).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(t('errors.invalid_credentials.what'))).toHaveCount(0)
  await expect(page).toHaveURL(/\/auth\/login$/)

  // ── разблокировать ────────────────────────────────────────────────────────
  await войти(page, админ)
  карточка = await открыть(жертва)
  await карточка.getByRole('button', { name: t('admin.card.unblock') }).click()
  const снятие = page.getByRole('dialog', { name: t('admin.card.unblockTitle') })
  await expect(снятие).toBeVisible()
  await снятие.getByRole('button', { name: t('admin.card.unblock') }).click()
  await expect(снятие).toHaveCount(0, { timeout: 30_000 })

  // ── и человек снова входит ────────────────────────────────────────────────
  await выйти(page)
  await войти(page, жертва)
})

/**
 * «Завести человека»: аккаунт без письма и без пароля, а вместо письма —
 * ссылка сброса, показанная администратору один раз.
 *
 * Писем служба не шлёт, поэтому единственный честный путь завести человека —
 * отдать администратору ссылку и передать её из рук в руки.
 * Проверяется путь целиком: ссылка выдана, по ней ставится пароль, с этим
 * паролем человек входит. Порознь ни один кусок ничего не доказывает — ссылка,
 * по которой войти нельзя, выглядит точно так же, как рабочая.
 */
test('заведённый владельцем ставит пароль по ссылке и входит', async ({ page }) => {
  test.setTimeout(180_000)
  const админ = await signUpAndLogin(page, 'creator')
  сделатьАдмином(админ)

  const новичок = uniqueEmail('created')
  const ник = nicknameFor(новичок)

  await page.goto('/admin/users')
  await page.getByRole('button', { name: t('admin.users.create') }).click()
  const окно = page.getByRole('dialog', { name: t('admin.create.title') })
  await окно.getByLabel(t('admin.create.email')).fill(новичок)
  await окно.getByLabel(t('admin.create.nickname')).fill(ник)
  await окно.getByRole('button', { name: t('admin.create.submit') }).click()

  // ── ссылка показана один раз ──────────────────────────────────────────────
  const показ = page.getByRole('dialog', { name: t('admin.create.onceTitle') })
  await expect(показ).toBeVisible({ timeout: 30_000 })
  const ссылка = (await показ.locator('code').innerText()).trim()
  expect(ссылка).toMatch(/\/reset\?token=/)
  await показ.getByRole('button', { name: t('common.action.close'), exact: true }).click()

  // Второй раз её не показывают: открытой служба её нигде не хранит.
  await expect(page.getByText(ссылка)).toHaveCount(0)

  // ── пароль ставится по ссылке ─────────────────────────────────────────────
  // Открывается путь из самой ссылки, а не собранный нами: имя сайта на стенде
  // другое (служба на своём порту, сайт на своём), а путь и токен — те самые.
  // Служба кладёт в ссылку `/reset?token=…` без приставки `auth`, и сайт обязан
  // такой адрес понимать (`features/auth/routes.tsx`).
  const адрес = new URL(ссылка)
  expect(адрес.searchParams.get('token')).toBeTruthy()

  await выйти(page)
  await page.goto(`${адрес.pathname}${адрес.search}`)
  await expect(page).toHaveURL(/\/auth\/reset\?token=/)
  await page.getByLabel(t('auth.field.passwordNew')).fill(PASSWORD)
  await page.getByLabel(t('auth.field.passwordRepeat')).fill(PASSWORD)
  await page.getByRole('button', { name: t('auth.reset.submit') }).click()
  await expect(page.getByText(t('auth.reset.okTitle'))).toBeVisible({ timeout: 30_000 })

  // ── и с этим паролем человек входит: почта заведена уже подтверждённой ────
  await войти(page, новичок)
  await page.goto('/')
  await expect(page.locator('h1').first()).toContainText(ник, { timeout: 30_000 })
})
