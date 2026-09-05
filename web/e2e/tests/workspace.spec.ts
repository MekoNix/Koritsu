/**
 * Пространства и поиск: второе пространство, приглашение второго человека,
 * роль, переключатель — и палитра `Ctrl+K`.
 *
 * Второй человек здесь настоящий: заводится своей регистрацией и своим
 * подтверждением почты, потому что приглашение — это участие сразу, а по
 * несуществующей почте служба отказывает (`no_such_user`, писем она не шлёт).
 * Подделать это нечем и незачем: весь смысл проверки в том, что двое видят одно
 * пространство.
 *
 * Прогонов модели ни одного: ни участники, ни поиск её не зовут.
 */
import { expect, test } from '@playwright/test'

import { login as войти, logout as выйти, nicknameFor, signUpAndLogin, t } from './helpers'

const ПРОСТРАНСТВО = 'Кафедра ИУ7'
const РАБОТА = 'Отчёт по практике'

test('пространство: второй человек, приглашение, роль, переключатель', async ({ page }) => {
  test.setTimeout(180_000)

  // Второго человека заводим первым: приглашать можно только того, у кого уже
  // есть аккаунт.
  const второй = await signUpAndLogin(page, 'ws-two')
  await выйти(page)
  const первый = await signUpAndLogin(page, 'ws-one')

  const переключатель = page.getByRole('button', { name: t('workspace.switcher.label') })
  // Пока пространство одно, и это личное — служба зовёт его `Personal`, сайт
  // показывает ник человека.
  await expect(переключатель).toContainText(nicknameFor(первый))

  // ── новое пространство ────────────────────────────────────────────────────
  await переключатель.click()
  await page.getByRole('menuitem', { name: t('workspace.switcher.create') }).click()
  const создание = page.getByRole('dialog', { name: t('workspace.create.title') })
  await создание.getByLabel(t('workspace.create.name')).fill(ПРОСТРАНСТВО)
  await создание.getByRole('button', { name: t('workspace.create.submit') }).click()

  // Заведённое становится текущим — иначе после заведения человек оказался бы
  // не там, куда шёл.
  await expect(переключатель).toContainText(ПРОСТРАНСТВО)

  // ── участники: приглашение по почте ───────────────────────────────────────
  await переключатель.click()
  await page.getByRole('menuitem', { name: t('workspace.switcher.manage') }).click()
  await expect(page).toHaveURL(/\/workspace$/)
  await expect(page.getByRole('heading', { name: ПРОСТРАНСТВО })).toBeVisible()

  await page.getByRole('button', { name: t('workspace.members.invite') }).click()
  const приглашение = page.getByRole('dialog', { name: t('workspace.invite.title') })
  await приглашение.getByLabel(t('workspace.invite.email')).fill(второй)
  await приглашение.getByLabel(t('workspace.invite.role')).selectOption('editor')
  await приглашение.getByRole('button', { name: t('workspace.invite.submit') }).click()

  // Окно закрывается само, строка появляется в таблице: писем нет, участие есть.
  await expect(приглашение).toHaveCount(0)
  const строка = page.getByRole('row').filter({ hasText: второй })
  await expect(строка).toBeVisible({ timeout: 30_000 })
  await expect(строка.getByRole('combobox')).toHaveValue('editor')

  // ── роль меняется и переживает перезагрузку ───────────────────────────────
  await строка.getByRole('combobox').selectOption('viewer')
  await page.reload()
  await expect(page.getByRole('row').filter({ hasText: второй }).getByRole('combobox')).toHaveValue(
    'viewer',
    { timeout: 30_000 },
  )

  // Почта, которой в службе нет, приглашению не поддаётся, и отказ садится в
  // поле, а не в ленту тостов.
  await page.getByRole('button', { name: t('workspace.members.invite') }).click()
  const второе = page.getByRole('dialog', { name: t('workspace.invite.title') })
  await второе.getByLabel(t('workspace.invite.email')).fill('никого-такого@example.org')
  await второе.getByRole('button', { name: t('workspace.invite.submit') }).click()
  await expect(второе.getByLabel(t('workspace.invite.email'))).toHaveAttribute(
    'aria-invalid',
    'true',
    { timeout: 30_000 },
  )
  await второе.getByRole('button', { name: t('workspace.cancel') }).click()

  // ── переключатель: два пространства, возврат в личное ─────────────────────
  await переключатель.click()
  const меню = page.getByRole('menu')
  await expect(меню.getByRole('menuitem', { name: ПРОСТРАНСТВО })).toBeVisible()
  await меню.getByRole('menuitem', { name: nicknameFor(первый) }).click()
  await expect(переключатель).toContainText(nicknameFor(первый))

  // ── второй человек видит то же пространство ───────────────────────────────
  await выйти(page)
  await войти(page, второй)
  const чужой = page.getByRole('button', { name: t('workspace.switcher.label') })
  await чужой.click()
  await expect(page.getByRole('menuitem', { name: ПРОСТРАНСТВО })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('menuitem', { name: ПРОСТРАНСТВО }).click()
  await expect(чужой).toContainText(ПРОСТРАНСТВО)

  // Роль наблюдателя видна ему самому и правами не наделяет: приглашать он не
  // может, и кнопки у него нет вовсе.
  // Роль названа в двух местах — в шапке пространства и своей строкой в
  // таблице участников, — поэтому спрашиваем строку, а не страницу: «где-то на
  // экране написано „наблюдатель“» не отвечает на вопрос, чья это роль.
  await page.goto('/workspace')
  await expect(page.getByRole('row').filter({ hasText: второй })).toContainText(
    t('workspace.role.viewer'),
    { timeout: 30_000 },
  )
  await expect(page.getByRole('button', { name: t('workspace.members.invite') })).toHaveCount(0)

  // Первый человек в списке участников у второго тоже виден.
  await expect(page.getByRole('row').filter({ hasText: первый })).toBeVisible()
})

test('поиск Ctrl+K находит работу и открывает её', async ({ page }) => {
  test.setTimeout(120_000)
  await signUpAndLogin(page, 'search')

  // Работа без шаблона: палитра ищет по именам, а не по содержимому.
  await page.getByRole('link', { name: t('shell.nav.projects') }).click()
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const создание = page.getByRole('dialog')
  await создание.getByLabel(t('projects.create.name')).fill(РАБОТА)
  await создание.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  // С дашборда — чтобы было видно, что палитра открывается откуда угодно.
  await page.goto('/')
  // Дождаться шапки, а не жать сразу: слушатель горячей клавиши ставит React
  // при монтировании, и нажатие в промежутке между загрузкой страницы и
  // монтированием пропадает бесследно.
  const кнопка = page.getByRole('button').filter({ hasText: t('shell.search.label') })
  await expect(кнопка).toBeVisible()
  await page.keyboard.press('Control+k')
  const палитра = page.getByRole('dialog', { name: t('search.title') })
  await expect(палитра).toBeVisible()

  // Пока не набрано — подсказка, а не пустой список «ничего не нашлось».
  await expect(палитра.getByText(t('search.hint'))).toBeVisible()

  const поле = палитра.getByPlaceholder(t('search.placeholder'))
  await поле.fill('практик')
  const найдено = палитра.getByRole('option', { name: new RegExp(РАБОТА) })
  await expect(найдено).toBeVisible({ timeout: 30_000 })

  // Ищет служба (`GET /api/search`), а не браузер, и ищет она по куску имени
  // без учёта регистра: набранное капсом («ПРАКТИК» в «Отчёт по практике»)
  // обязано находить то же самое. Проверяется именно это: раньше палитра
  // отбирала загруженный список сама, и правило совпадения было её,
  // а не службы.
  await поле.fill('ПРАКТИК')
  await expect(найдено).toBeVisible({ timeout: 30_000 })

  // Того, чего нет, палитра не выдумывает.
  await поле.fill('этого-точно-нет')
  await expect(палитра.getByText(t('search.nothing', { query: 'этого-точно-нет' }))).toBeVisible()

  // Выбор клавиатурой — палитра для того и заведена. Первая строка выбрана
  // сразу, поэтому хватает `Enter`: стрелка на списке из одной строки увела бы
  // проверку в проверку кольцевого перебора, а не открытия.
  await поле.fill('практик')
  await expect(найдено).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`))
  await expect(палитра).toHaveCount(0)
})
