/**
 * Админка: её видит только тот, у кого право есть.
 *
 * Право выдаётся тем же способом, каким его выдаёт владелец на боевой машине, —
 * строкой в базе (`UPDATE users SET is_admin=1`). Ручки «сделай меня админом» у
 * службы нет и заводить её нельзя: она и была бы дырой, ради закрытия которой
 * весь `/api/admin` закрыт `require_admin`.
 *
 * Проверяется ровно то, что нельзя проверить ни в службе, ни в vitest: сайт
 * узнаёт право из `is_admin` в `GET /api/auth/me`, показывает `/admin` и
 * по-прежнему не показывает ссылку на него ни в меню, ни на дашборде.
 */
import { execFileSync } from 'node:child_process'

import { expect, test } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'
import { DB_FILE } from './stand'

/** Выдать право администратора прямо в базе тома. */
function сделатьАдмином(email: string): void {
  const python = process.env.PYTHON ?? '/home/kurisu/koritsu2/.venv/bin/python'
  execFileSync(
    python,
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

test('право администратора открывает /admin и не появляется в меню', async ({ page }) => {
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

  // И главное: ссылки на админку в оболочке нет ни у кого — попасть сюда можно
  // только прямым адресом (правка 2 макетов).
  await page.goto('/')
  await expect(page.locator('aside').getByRole('link', { name: t('shell.nav.admin') })).toHaveCount(
    0,
  )
  await expect(page.locator('a[href="/admin"]')).toHaveCount(0)
})
