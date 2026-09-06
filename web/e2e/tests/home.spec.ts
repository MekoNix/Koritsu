/**
 * Первый и последний экраны человека: страница входа, лента дашборда, аватар.
 *
 * Всё три — про то, что видно глазами и не видно ни одной другой проверке.
 *
 * 1. **Страница входа.** Обещание продукта — короткая строка про набор
 *    инструментов, и она приезжает из словаря, а не из макета. Проверяется
 *    тем, что заголовок с этим текстом виден рядом с формой: заголовок,
 *    уехавший под форму или за край, — та же поломка, что и пропавший.
 * 2. **Правка ленты.** Ручки и крестики бывают только в режиме правки, клетку
 *    можно убрать и вернуть, а порядок и убранные помнятся браузером. Память
 *    здесь и есть главное: она живёт в `localStorage`, и ни `tests/api`, ни
 *    vitest её не трогают — ломается она молча и у человека.
 * 3. **Свой аватар.** Загруженная картинка обязана появиться в шапке сразу,
 *    пережить перезагрузку (значит, она пришла из профиля, а не из состояния
 *    вкладки) и исчезнуть после «Убрать», уступив генеративной решётке.
 *
 * Картинка для загрузки рисуется на месте (Pillow из общего venv), а не лежит
 * в репозитории двоичным файлом: так видно, что именно отправляется, и
 * невидно, чем это отличается от того, что вернёт служба.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { signUpAndLogin, t, перейти } from './helpers'
import { PYTHON, STAND_DIR } from './stand'

/**
 * Не квадратный JPEG в томе стенда: служба обрежет его по центру и пересохранит
 * в PNG, и по формату ответа видно, что пересохранение случилось.
 */
function аватарФайл(): string {
  const файл = path.join(STAND_DIR, 'аватар-проверки.jpg')
  if (fs.existsSync(файл)) return файл
  execFileSync(
    PYTHON,
    [
      '-c',
      [
        'import sys',
        'from PIL import Image',
        'Image.new("RGB", (300, 200), "#3355aa").save(sys.argv[1], format="JPEG")',
      ].join('\n'),
      файл,
    ],
    { stdio: 'pipe' },
  )
  return файл
}

/** Имена клеток в том порядке, в каком они сейчас на ленте. Только в режиме правки. */
async function порядокЛенты(page: Page): Promise<string[]> {
  return page
    .locator('[data-cell]')
    .evaluateAll((узлы) => узлы.map((узел) => узел.getAttribute('data-cell') ?? ''))
}

test.describe('первый экран', () => {
  test('страница входа обещает набор инструментов', async ({ page }) => {
    await перейти(page, '/auth/login')

    // Обещание и форма — на одном экране: левая половина не должна ни закрывать
    // форму, ни уезжать за край.
    await expect(page.getByRole('heading', { name: t('auth.hero.title') })).toBeVisible()
    await expect(page.getByText(t('auth.hero.text'))).toBeVisible()
    await expect(page.getByRole('button', { name: t('auth.login.submit') })).toBeVisible()
  })

  test('лента правится: клетку убирают, возвращают, порядок помнится', async ({ page }) => {
    await signUpAndLogin(page, 'dashboard')
    await перейти(page, '/')

    // Клетка ищется заголовком плитки, а не текстом внутри: в режиме правки
    // то же имя стоит на кнопке «вернуть», и по тексту они были бы неотличимы.
    const работы = page.getByRole('heading', { name: t('dashboard.works.title') })
    await expect(работы).toBeVisible()
    // Вне режима правки ни ручек, ни крестиков: лента — просто лента.
    await expect(page.locator('[data-cell]')).toHaveCount(0)
    await expect(page.locator('[data-hide]')).toHaveCount(0)

    await page.getByRole('button', { name: t('dashboard.edit.start') }).click()
    // Сколько клеток бывает — считаем, а не пишем числом: список клеток растёт
    // с каждым новым модулем, и проверка правки ленты не должна падать от этого.
    const всего = await page.locator('[data-cell]').count()
    expect(всего).toBeGreaterThan(1)

    // Убрать клетку: она уходит с ленты и появляется в списке убранных.
    await page.locator('[data-hide="works"]').click()
    await expect(работы).toHaveCount(0)
    await expect(page.locator('[data-cell]')).toHaveCount(всего - 1)
    await expect(page.locator('[data-restore="works"]')).toBeVisible()

    // Перезагрузка помнит убранное — иначе «убрать» было бы правкой до первого F5.
    await page.reload()
    await expect(page.getByRole('button', { name: t('dashboard.edit.start') })).toBeVisible()
    await expect(работы).toHaveCount(0)

    await page.getByRole('button', { name: t('dashboard.edit.start') }).click()
    await page.locator('[data-restore="works"]').click()
    await expect(работы).toBeVisible()
    await expect(page.locator('[data-cell]')).toHaveCount(всего)

    // Порядок: первую клетку двигаем стрелкой (то же, что перетаскиванием, но
    // без мыши — раскладка обязана меняться и с клавиатуры).
    const было = await порядокЛенты(page)
    await page.locator(`[data-cell="${было[0]}"]`).press('ArrowRight')
    const стало = await порядокЛенты(page)
    expect(стало[0]).toBe(было[1])
    expect(стало[1]).toBe(было[0])

    // И этот порядок переживает перезагрузку.
    await page.reload()
    await page.getByRole('button', { name: t('dashboard.edit.start') }).click()
    expect(await порядокЛенты(page)).toEqual(стало)

    // «Готово» убирает ручки — режим кончается.
    await page.getByRole('button', { name: t('dashboard.edit.done') }).click()
    await expect(page.locator('[data-cell]')).toHaveCount(0)
  })

  test('свой аватар виден в шапке, а «Убрать» возвращает генеративный', async ({ page }) => {
    await signUpAndLogin(page, 'avatar')
    await перейти(page, '/settings/profile')

    // Шапка — там же, где аватар виден всё время; в профиле он свой, и путать
    // одно с другим нельзя, поэтому проверка ходит именно в кнопку меню.
    const шапка = page.getByRole('button', { name: t('shell.user.menu') })
    await expect(шапка).toBeVisible()
    // Своей картинки нет — рисуется решётка, то есть `<img>` в шапке нет вовсе.
    await expect(шапка.locator('img')).toHaveCount(0)

    await page.getByLabel(t('settings.profile.avatarFile')).setInputFiles(аватарФайл())

    // Появилась сразу, без перезагрузки: ответ загрузки кладётся в тот же кэш
    // профиля, который читает шапка.
    await expect(шапка.locator('img')).toBeVisible()
    await expect(шапка.locator('img')).toHaveAttribute(
      'src',
      /\/api\/users\/[0-9a-fA-F-]+\/avatar\?v=1$/,
    )

    // Пережила перезагрузку — значит, приехала из профиля, а не из состояния вкладки.
    await page.reload()
    await expect(шапка.locator('img')).toBeVisible()

    await page.getByRole('button', { name: t('settings.profile.avatarRemove') }).click()
    await expect(шапка.locator('img')).toHaveCount(0)
    // Кнопки «Убрать» больше нет: убирать нечего.
    await expect(
      page.getByRole('button', { name: t('settings.profile.avatarRemove') }),
    ).toHaveCount(0)
  })
})
