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

import { I18N_DIR, SERVE_LOG, STAND_DIR } from './stand'

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

// ── человек ──────────────────────────────────────────────────────────────────

/** Пароль стенда: длиннее десяти знаков, как требует служба. */
export const PASSWORD = 'Пароль-стенда-2026'

/** Почта, которой ещё не было: том общий, а человек у каждой проверки свой. */
export function uniqueEmail(prefix: string): string {
  const хвост = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`
  return `web-${prefix}-${хвост}@example.org`
}

/** Все токены подтверждения, какие есть в журнале службы, по порядку. */
function tokensInLog(): string[] {
  if (!fs.existsSync(SERVE_LOG)) return []
  const log = fs.readFileSync(SERVE_LOG, 'utf8')
  return [...log.matchAll(/confirm\?token=([A-Za-z0-9._-]+)/g)].map((m) => m[1] as string)
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
  const было = tokensInLog().length

  await page.goto('/auth/register')
  await page.getByLabel(t('auth.field.email')).fill(email)
  await page.getByLabel(t('auth.field.password'), { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: t('auth.register.submit') }).click()
  await expect(page.getByText(t('auth.register.sentTitle'))).toBeVisible()

  await expect.poll(() => tokensInLog().length, { timeout: 15_000 }).toBeGreaterThan(было)
  const token = tokensInLog().at(-1) as string

  await page.goto(`/auth/confirm?token=${encodeURIComponent(token)}`)
  await expect(page.getByText(t('auth.confirm.okTitle'))).toBeVisible()

  await page.goto('/auth/login')
  await page.getByLabel(t('auth.field.email')).fill(email)
  await page.getByLabel(t('auth.field.password'), { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: t('auth.login.submit') }).click()

  // Признак входа — оболочка: сайдбар с пунктом «Проекты» есть только внутри.
  await expect(page.getByRole('link', { name: t('shell.nav.projects') })).toBeVisible()
  return email
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
  const python = process.env.PYTHON ?? '/home/kurisu/koritsu2/.venv/bin/python'
  execFileSync(
    python,
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
