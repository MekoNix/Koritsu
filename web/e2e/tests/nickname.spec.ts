/**
 * Ник: как человека зовут на экране от регистрации до участников пространства.
 *
 * У службы есть поле `nickname` и `PATCH /api/auth/me`, а у сайта — четыре
 * места, где ник заменил почту: приветствие на дашборде, меню имени в шапке,
 * имя личного пространства и строка участника. Проверять их порознь
 * нечем: каждое по отдельности — одно поле из `me`, а вместе они отвечают на
 * вопрос «переименовался ли человек везде, где его зовут по имени». Разъезжается
 * это ровно на правке ника, поэтому ник здесь и правится.
 *
 * Почта на дашборде показана частично (`lib/maskEmail`): экран открывают при
 * других людях.
 *
 * Прогонов модели ни одного.
 */
import { expect, test } from '@playwright/test'

import { nicknameFor, signUpAndLogin, t } from './helpers'

test('ник: приветствие, меню, правка в профиле, участники', async ({ page }) => {
  test.setTimeout(120_000)
  const email = await signUpAndLogin(page, 'nick')
  const ник = nicknameFor(email)

  // ── дашборд: приветствие ником, почта частично скрыта ─────────────────────
  await page.goto('/')
  const приветствие = page.locator('h1').first()
  await expect(приветствие).toContainText(ник, { timeout: 30_000 })
  // Почта — «a***@example.org»: ни имени целиком, ни его длины.
  const хвост = email.slice(email.lastIndexOf('@'))
  await expect(page.getByText(`${email[0] as string}***${хвост}`)).toBeVisible()
  await expect(page.getByText(email, { exact: true })).toHaveCount(0)

  // ── шапка: меню человека названо ником ────────────────────────────────────
  const меню = page.getByRole('button', { name: t('shell.user.menu') })
  await expect(меню).toContainText(ник)

  // ── личное пространство названо ником, а не словом службы «Personal» ──────
  const переключатель = page.getByRole('button', { name: t('workspace.switcher.label') })
  await expect(переключатель).toContainText(ник)

  // ── правка ника в профиле ─────────────────────────────────────────────────
  const новый = `${ник}-2`.slice(0, 32)
  await page.goto('/settings/profile')
  const поле = page.getByLabel(t('settings.profile.nickname'))
  await expect(поле).toHaveValue(ник, { timeout: 30_000 })

  // Кривой ник останавливает форма, а не служба: пробел в нике — не повод для
  // похода на сервер.
  await поле.fill('два слова')
  await page.getByRole('button', { name: t('settings.profile.save') }).click()
  await expect(page.getByText(t('settings.valid.nicknameChars'))).toBeVisible()

  await поле.fill(новый)
  await page.getByRole('button', { name: t('settings.profile.save') }).click()
  // Имя над формой берётся из `me`, а не из поля: значит правка доехала до
  // службы и вернулась перечитанным профилем.
  await expect(page.getByText(новый, { exact: true }).first()).toBeVisible({ timeout: 30_000 })

  // ── новое имя всюду, где человека зовут по имени ──────────────────────────
  await expect(меню).toContainText(новый, { timeout: 30_000 })
  await expect(переключатель).toContainText(новый)

  await page.goto('/')
  await expect(приветствие).toContainText(новый, { timeout: 30_000 })

  // Участники: ник крупно, почта под ним — это одна и та же строка таблицы.
  await page.goto('/workspace')
  const строка = page.getByRole('row').filter({ hasText: email })
  await expect(строка).toBeVisible({ timeout: 30_000 })
  await expect(строка).toContainText(новый)

  // Ник переживает перезагрузку: он в службе, а не в браузере.
  await page.reload()
  await expect(page.getByRole('row').filter({ hasText: email })).toContainText(новый, {
    timeout: 30_000,
  })
})
