/**
 * Приглашение как дело, а не как зачисление — и то, что переключение
 * пространства меняет весь экран.
 *
 * Три вещи, ради которых написана эта проверка, и все три раньше человек
 * увидел бы только глазами:
 *
 * 1. **приглашение приходит уведомлением с двумя кнопками.** До ответа
 *    пространства для позванного не существует: его нет ни в переключателе, ни
 *    у службы (`role_of` не считает `pending` участием). «Принять» уносит строку
 *    колокольчика — приглашения, на которое уже ответили, не бывает;
 * 2. **переключение пространства меняет списки.** Работа, заведённая в одном
 *    пространстве, во втором не показывается — и не показывается **без
 *    перезагрузки страницы**: перезагрузка спрятала бы ровно ту беду, ради
 *    которой проверка и написана;
 * 3. **уведомление можно убрать.** Колокольчик — не архив.
 *
 * Прогонов модели здесь нет ни одного: ни приглашение, ни переключатель её не
 * зовут. Работа заводится без шаблона — списку она нужна как строка, а не как
 * документ.
 */
import { expect, test } from '@playwright/test'

import { login as войти, logout as выйти, nicknameFor, signUpAndLogin, t } from './helpers'

const ПРОСТРАНСТВО = 'Лаборатория 12'
const РАБОТА = 'Работа лаборатории'

test('приглашение: уведомление, принять, переключение обновляет списки', async ({ page }) => {
  test.setTimeout(180_000)

  // Позванного заводим первым: зовут по почте, у которой уже есть аккаунт.
  const позванный = await signUpAndLogin(page, 'inv-two')
  await выйти(page)
  const хозяин = await signUpAndLogin(page, 'inv-one')

  const переключатель = page.getByRole('button', { name: t('workspace.switcher.label') })
  // Кнопка отвечает на «где я»: над именем стоит слово «Пространство».
  await expect(переключатель).toContainText(t('workspace.switcher.caption'))
  // Личное пространство зовётся ником хозяина: `<ник>-workspace`.
  await expect(переключатель).toContainText(nicknameFor(хозяин))

  // ── общее пространство и работа в нём ─────────────────────────────────────
  await переключатель.click()
  await page.getByRole('menuitem', { name: t('workspace.switcher.create') }).click()
  const создание = page.getByRole('dialog', { name: t('workspace.create.title') })
  await создание.getByLabel(t('workspace.create.name')).fill(ПРОСТРАНСТВО)
  await создание.getByRole('button', { name: t('workspace.create.submit') }).click()
  await expect(переключатель).toContainText(ПРОСТРАНСТВО)

  await page.goto('/projects')
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('projects.create.name')).fill(РАБОТА)
  await окно.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)

  // ── переключение меняет список работ, и без перезагрузки ──────────────────
  await page.goto('/projects')
  await expect(page.getByText(РАБОТА).first()).toBeVisible({ timeout: 30_000 })

  await переключатель.click()
  await page.getByRole('menuitem', { name: nicknameFor(хозяин) }).click()
  await expect(переключатель).toContainText(nicknameFor(хозяин))
  // Личное пусто: работа осталась в общем пространстве.
  await expect(page.getByText(t('projects.list.empty'))).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(РАБОТА)).toHaveCount(0)

  await переключатель.click()
  await page.getByRole('menuitem', { name: ПРОСТРАНСТВО }).click()
  await expect(page.getByText(РАБОТА).first()).toBeVisible({ timeout: 30_000 })

  // ── приглашение ──────────────────────────────────────────────────────────
  await page.goto('/workspace')
  await page.getByRole('button', { name: t('workspace.members.invite') }).click()
  const приглашение = page.getByRole('dialog', { name: t('workspace.invite.title') })
  await приглашение.getByLabel(t('workspace.invite.email')).fill(позванный)
  await приглашение.getByLabel(t('workspace.invite.role')).selectOption('editor')
  await приглашение.getByRole('button', { name: t('workspace.invite.submit') }).click()
  await expect(приглашение).toHaveCount(0)

  // Владелец видит позванного помеченным: «позвал, а его нет» — не состояние.
  const строка = page.getByRole('row').filter({ hasText: позванный })
  await expect(строка).toContainText(t('workspace.members.pending'), { timeout: 30_000 })

  // ── позванный отвечает ───────────────────────────────────────────────────
  await выйти(page)
  await войти(page, позванный)
  const чужой = page.getByRole('button', { name: t('workspace.switcher.label') })

  // Пространства у него ещё нет: приглашение не зачисляет.
  await чужой.click()
  await expect(page.getByRole('menuitem', { name: ПРОСТРАНСТВО })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.goto('/projects')
  await expect(page.getByText(РАБОТА)).toHaveCount(0)

  // Колокольчик берём из шапки: имя «Уведомления» носит ещё и клетка дашборда.
  const колокольчик = page
    .getByRole('banner')
    .getByRole('button', { name: t('shell.notifications.label') })
  await колокольчик.click()
  const меню = page.getByRole('menu')
  await expect(меню.getByText(t('notifications.invite.title', { name: ПРОСТРАНСТВО }))).toBeVisible(
    {
      timeout: 30_000,
    },
  )
  await меню.getByRole('button', { name: t('notifications.invite.accept') }).click()

  // Ответ уносит строку: кнопок, которые больше ничего не сделают, не остаётся.
  await expect(меню.getByRole('button', { name: t('notifications.invite.accept') })).toHaveCount(
    0,
    {
      timeout: 30_000,
    },
  )
  await page.keyboard.press('Escape')

  // Теперь пространство есть, и работа хозяина в нём видна.
  await чужой.click()
  await page.getByRole('menuitem', { name: ПРОСТРАНСТВО }).click()
  await expect(чужой).toContainText(ПРОСТРАНСТВО)
  await expect(page.getByText(РАБОТА).first()).toBeVisible({ timeout: 30_000 })
})

test('приглашение можно отклонить, а уведомление — убрать', async ({ page }) => {
  test.setTimeout(180_000)

  const позванный = await signUpAndLogin(page, 'dec-two')
  await выйти(page)
  await signUpAndLogin(page, 'dec-one')

  const переключатель = page.getByRole('button', { name: t('workspace.switcher.label') })
  await переключатель.click()
  await page.getByRole('menuitem', { name: t('workspace.switcher.create') }).click()
  const создание = page.getByRole('dialog', { name: t('workspace.create.title') })
  await создание.getByLabel(t('workspace.create.name')).fill('Комната отказа')
  await создание.getByRole('button', { name: t('workspace.create.submit') }).click()
  await expect(переключатель).toContainText('Комната отказа')

  await page.goto('/workspace')
  await page.getByRole('button', { name: t('workspace.members.invite') }).click()
  const приглашение = page.getByRole('dialog', { name: t('workspace.invite.title') })
  await приглашение.getByLabel(t('workspace.invite.email')).fill(позванный)
  await приглашение.getByRole('button', { name: t('workspace.invite.submit') }).click()
  await expect(приглашение).toHaveCount(0)
  await expect(page.getByRole('row').filter({ hasText: позванный })).toBeVisible({
    timeout: 30_000,
  })

  await выйти(page)
  await войти(page, позванный)

  // Колокольчик берём из шапки: имя «Уведомления» носит ещё и клетка дашборда.
  const колокольчик = page
    .getByRole('banner')
    .getByRole('button', { name: t('shell.notifications.label') })
  await колокольчик.click()
  const меню = page.getByRole('menu')
  await expect(
    меню.getByText(t('notifications.invite.title', { name: 'Комната отказа' })),
  ).toBeVisible({ timeout: 30_000 })
  await меню.getByRole('button', { name: t('notifications.invite.decline') }).click()

  // Отказ уносит и строку колокольчика, и участие: пространства не появилось.
  await expect(меню.getByRole('button', { name: t('notifications.invite.decline') })).toHaveCount(
    0,
    { timeout: 30_000 },
  )
  await page.keyboard.press('Escape')
  await переключатель.click()
  await expect(page.getByRole('menuitem', { name: 'Комната отказа' })).toHaveCount(0)
  await page.keyboard.press('Escape')

  // ── уведомление убирается ────────────────────────────────────────────────
  // Своё пространство и своя работа — чтобы в колокольчике появилась строка о
  // законченном задании: разбор принесённого файла её и заводит.
  await page.goto('/projects')
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('projects.create.name')).fill('Работа с файлом')
  await окно.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)

  await page
    .locator('input[type="file"]')
    .first()
    .setInputFiles({
      name: 'условие.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Текст условия для разбора.', 'utf8'),
    })

  await колокольчик.click()
  const строки = page.getByRole('menu').getByRole('menuitem')
  await expect(строки.first()).toContainText(t('notifications.jobDone'), { timeout: 120_000 })
  const было = await строки.count()

  await строки
    .first()
    .getByRole('button', { name: t('notifications.delete') })
    .click()
  await expect(строки).toHaveCount(было - 1, { timeout: 30_000 })
})
