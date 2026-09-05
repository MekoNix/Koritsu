/**
 * Админка живёт на своём имени, и с чужого её нет.
 *
 * Проверяется то, чего не увидеть ни в службе, ни в vitest: одно и то же
 * приложение на одном и том же стенде ведёт себя по-разному на двух именах.
 * Стенд поднят с `KORITSU_ADMIN_DOMAIN=127.0.0.1` (`web/e2e/stack.sh`), и оба
 * имени ведут в него же:
 *
 *   http://127.0.0.1:<порт>   имя админки — админка открывается
 *   http://localhost:<порт>   чужое имя — «страница не найдена» и 404 у API
 *
 * Второе окно — свой контекст браузера, а не второй адрес в том же: origin у
 * имён разный, значит и cookie сессии разная. Это не обход проверки, а ровно то
 * свойство, ради которого админку и вынесли на своё имя, — вошедший на сайт не
 * оказывается вошедшим в админку заодно.
 *
 * Право администратора выдаётся так же, как на боевой машине, — строкой в базе
 * тома: ручки «сделай меня админом» у службы нет и заводить её нельзя.
 */
import { execFileSync } from 'node:child_process'

import { expect, test } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'
import { DB_FILE, PYTHON, WEB_PORT } from './stand'

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

test('админка открыта на своём имени и не существует на чужом', async ({ browser, page }) => {
  // ── своё имя: всё как обычно ───────────────────────────────────────────────
  const свой = await signUpAndLogin(page, 'admindomain')
  сделатьАдмином(свой)

  const профиль = await (await page.request.get('/api/auth/me')).json()
  const домен: string = профиль.admin_domain ?? ''
  test.skip(!домен, 'стенд поднят без KORITSU_ADMIN_DOMAIN — делить нечего')

  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: t('admin.title') })).toBeVisible()

  // Пункт админки в меню пользователя есть — и только у владельца службы.
  await page.getByRole('button', { name: t('shell.user.menu') }).click()
  await expect(page.getByRole('menuitem', { name: t('shell.user.admin') })).toBeVisible()
  await page.keyboard.press('Escape')

  // ── чужое имя: тот же стенд, другой `Host` ─────────────────────────────────
  const чужой = await browser.newContext({ baseURL: `http://localhost:${WEB_PORT}` })
  try {
    const вторая = await чужой.newPage()
    const второй = await signUpAndLogin(вторая, 'admindomain-alien')
    // Право есть и у него: отказ обязан быть про имя, а не про права.
    сделатьАдмином(второй)

    // Служба: маршрута не существует. Не 403 — на этом имени его нет ни для кого.
    const ответ = await вторая.request.get('/api/admin/users')
    expect(ответ.status()).toBe(404)
    expect((await ответ.json()).error.code).toBe('not_found')

    // Сайт говорит то же самое: «страница не найдена», а не «нет доступа».
    await вторая.goto('/admin')
    await expect(вторая.getByText(t('common.state.notFound'))).toBeVisible()
    await expect(вторая.getByRole('heading', { name: t('admin.title') })).toHaveCount(0)

    // Остальной сайт на этом имени работает: закрыта админка, а не вход.
    await вторая.goto('/')
    await expect(вторая.getByRole('button', { name: t('shell.user.menu') })).toBeVisible()
  } finally {
    await чужой.close()
  }
})
