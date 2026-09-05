/**
 * helpers — то, без чего не начинается ни одна сквозная проверка: словарь,
 * свой человек и вход через настоящие экраны.
 *
 * Три правила, которых здесь придерживаемся.
 *
 * 1. **Тексты — ключами перевода.** `t('auth.login.submit')`, а не «Войти».
 *    Словарь читается прямо из `src/i18n/ru/*.json` тем же способом, каким его
 *    собирает сайт (имя файла — приставка ключа), поэтому правка слова в
 *    словаре не ломает ни одной проверки.
 * 2. **Свой человек на каждую проверку.** Том у стенда общий, а вошедший —
 *    состояние; почта с отметкой времени, лимит регистраций на стенде поднят
 *    до тысячи (`web/e2e/README.md`).
 * 3. **Подтверждение почты — тем же путём, что у человека.** Токен вылавливается
 *    из журнала службы (в `dev` письма печатаются в него), и ссылка открывается
 *    браузером. Отдельной «ручки для тестов» у службы нет и заводить её нельзя.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { expect, type Page } from '@playwright/test'

import { I18N_DIR, PYTHON, SERVE_LOG, STAND_DIR } from './stand'

// ── словарь ──────────────────────────────────────────────────────────────────

type Tree = { [k: string]: string | Tree }

function flatten(tree: Tree, prefix: string, out: Record<string, string>): void {
  for (const [key, value] of Object.entries(tree)) {
    const full = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out[full] = value
    else flatten(value, full, out)
  }
}

const dictionary: Record<string, string> = (() => {
  const out: Record<string, string> = {}
  for (const имя of fs.readdirSync(I18N_DIR).sort()) {
    if (!имя.endsWith('.json')) continue
    const область = имя.replace(/\.json$/, '')
    flatten(JSON.parse(fs.readFileSync(path.join(I18N_DIR, имя), 'utf8')) as Tree, область, out)
  }
  return out
})()

/** Перевод по ключу — тот же разбор подстановок, что у сайта (`src/i18n`). */
export function t(key: string, vars?: Record<string, string | number>): string {
  const text = dictionary[key]
  if (text === undefined) throw new Error(`нет ключа перевода: ${key}`)
  if (!vars) return text
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  )
}

// ── переходы ─────────────────────────────────────────────────────────────────

/**
 * Переход по адресу сайта — с учётом того, что сайт может жить под префиксом
 * пути.
 *
 * `page.goto('/что-то')` Playwright склеивает через `new URL`, а абсолютный
 * путь стирает из адреса всё, что стояло до него: под `baseURL`
 * `…:4173/проба/` такой переход уходит на `…:4173/что-то`, то есть мимо сайта.
 * На дев-сервере это незаметно (префикса нет), а на боевой сборке — ровно та
 * беда, которую ищет `dist.spec.ts`. Поэтому путь приклеивается относительным.
 */
export async function перейти(page: Page, путь: string): Promise<void> {
  const относительный = путь.replace(/^\/+/, '')
  await page.goto(относительный === '' ? './' : относительный)
}

// ── человек ──────────────────────────────────────────────────────────────────

/** Пароль стенда: длиннее десяти знаков, как требует служба. */
export const PASSWORD = 'Пароль-стенда-2026'

/** Почта, которой ещё не было: том общий, а человек у каждой проверки свой. */
export function uniqueEmail(prefix: string): string {
  const хвост = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`
  return `web-${prefix}-${хвост}@example.org`
}

/**
 * Ник по почте: имя до `@`, обрезанное до предела службы (32 знака).
 *
 * Ник обязателен при регистрации и уникален без учёта регистра, а том
 * у проверок общий — значит выдумывать его нельзя, он должен быть таким же
 * одноразовым, как почта. Из почты он и берётся.
 */
export function nicknameFor(email: string): string {
  return (email.split('@')[0] as string).slice(0, 32)
}

/**
 * Все ссылки подтверждения из журнала службы, по порядку и целиком.
 *
 * Целиком, а не одним токеном: ссылку человек получает такой, какой её собрала
 * служба (`accounts/mail.py`), и открывает как есть. Собирать адрес страницы
 * самим значило бы проверять свою же догадку о том, куда письмо ведёт, — и не
 * заметить, что оно ведёт не туда.
 */
function linksInLog(): string[] {
  if (!fs.existsSync(SERVE_LOG)) return []
  const log = fs.readFileSync(SERVE_LOG, 'utf8')
  return [...log.matchAll(/https?:\/\/\S*confirm\?token=[A-Za-z0-9._-]+/g)].map((m) => m[0])
}

/**
 * Регистрация, подтверждение почты и вход — настоящими экранами.
 *
 * Токен ждём появления в журнале, а не читаем сразу: письмо печатается уже
 * после ответа службы, и «прочитать немедленно» иногда даёт токен прошлого
 * человека. Отсчёт ведётся от числа токенов ДО регистрации — это и есть
 * признак «пришёл новый».
 */
export async function signUpAndLogin(page: Page, prefix: string): Promise<string> {
  const email = uniqueEmail(prefix)
  const было = linksInLog().length

  await перейти(page, '/auth/register')
  await page.getByLabel(t('auth.field.email')).fill(email)
  await page.getByLabel(t('auth.field.nickname')).fill(nicknameFor(email))
  await page.getByLabel(t('auth.field.password'), { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: t('auth.register.submit') }).click()
  await expect(page.getByText(t('auth.register.sentTitle'))).toBeVisible()

  await expect.poll(() => linksInLog().length, { timeout: 15_000 }).toBeGreaterThan(было)
  const ссылка = new URL(linksInLog().at(-1) as string)

  // Открывается путь из письма, а не выдуманный нами: имя сайта на стенде
  // другое (служба на своём порту, сайт на своём), а путь и токен — те самые.
  await перейти(page, `${ссылка.pathname}${ссылка.search}`)
  await expect(page.getByText(t('auth.confirm.okTitle'))).toBeVisible()

  await перейти(page, '/auth/login')
  await page.getByLabel(t('auth.field.email')).fill(email)
  await page.getByLabel(t('auth.field.password'), { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: t('auth.login.submit') }).click()

  // Признак входа — оболочка: сайдбар с пунктом «Проекты» есть только внутри.
  await expect(page.getByRole('link', { name: t('shell.nav.projects') })).toBeVisible()
  return email
}

/**
 * Выход — через меню человека, тем же путём, каким выходит человек.
 *
 * Не `context.clearCookies()`: очистка кук оставила бы в браузере кэш профиля и
 * проверяла бы не выход, а забывчивость. Здесь же проверяется, что после выхода
 * закрытые экраны закрыты.
 */
export async function logout(page: Page): Promise<void> {
  await перейти(page, '/')
  await page.getByRole('button', { name: t('shell.user.menu') }).click()
  await page.getByRole('menuitem', { name: t('shell.user.logout') }).click()
  await expect(page).toHaveURL(/\/auth\/login$/)
}

/** Вход уже заведённым человеком. Пароль стенда один на всех. */
export async function login(page: Page, email: string, password = PASSWORD): Promise<void> {
  await перейти(page, '/auth/login')
  await page.getByLabel(t('auth.field.email')).fill(email)
  await page.getByLabel(t('auth.field.password'), { exact: true }).fill(password)
  await page.getByRole('button', { name: t('auth.login.submit') }).click()
  await expect(page.getByRole('link', { name: t('shell.nav.projects') })).toBeVisible()
}

// ── шаблон DOCX ──────────────────────────────────────────────────────────────

/** Теги того шаблона, что строит `templateDocx()`. */
export const TAG_ONE = 'цель'
export const TAG_TWO = 'выводы'

/**
 * Шаблон DOCX с двумя тегами — тот же, что собирает `smoke.sh`, и тем же
 * способом: `python-docx` из общего venv. Двоичный файл в репозитории вместо
 * этих десяти строк прятал бы главное — из чего у проекта берутся теги.
 *
 * Файл строится один раз на весь прогон и лежит в томе стенда, а не в дереве
 * репозитория: он такой же временный, как база.
 */
export function templateDocx(): string {
  const файл = path.join(STAND_DIR, 'шаблон-проверки.docx')
  if (fs.existsSync(файл)) return файл
  execFileSync(
    PYTHON,
    [
      '-c',
      [
        'import sys',
        'from docx import Document',
        'документ = Document()',
        'документ.add_paragraph("Отчёт по практике")',
        `for ключ in ("${TAG_ONE}", "${TAG_TWO}"):`,
        '    документ.add_paragraph("{{%s}}" % ключ)',
        'документ.save(sys.argv[1])',
      ].join('\n'),
      файл,
    ],
    { stdio: 'pipe' },
  )
  return файл
}
