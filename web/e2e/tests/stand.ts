/**
 * stand — где стоит стенд сквозных проверок и на каких портах.
 *
 * Один файл на всех: его читает и `playwright.config.ts` (чтобы поднять стенд
 * и сайт), и сами проверки (чтобы вычитать токен подтверждения из журнала
 * службы и сходить в базу тома за правом администратора). Разъехаться этим
 * числам нельзя — иначе проверка ищет журнал не того стенда.
 *
 * Порты — умолчания службы плюс десять на подделку: 8000 и 8010, сайт на 5170.
 * Всё переопределяется окружением, чтобы стенд
 * можно было поднять рядом с чужим.
 */
import fs from 'node:fs'
import path from 'node:path'

/** Порт настоящей службы (`api serve`). */
export const API_PORT = Number(process.env.API_PORT ?? 8000)

/** Порт поддельной модели (`e2e/fake-llm/server.py`). */
export const FAKE_PORT = Number(process.env.FAKE_PORT ?? API_PORT + 10)

/** Порт дев-сервера сайта. */
export const WEB_PORT = Number(process.env.WEB_PORT ?? 5170)

export const BASE_URL = `http://127.0.0.1:${WEB_PORT}`
export const API_URL = `http://127.0.0.1:${API_PORT}`

/**
 * Том стенда: база, файлы проектов и журналы. Не `/data` и не каталог
 * репозитория — стенд поднимается и сносится по многу раз.
 */
export const STAND_DIR = process.env.KORITSU_E2E_DIR ?? '/tmp/koritsu-web-e2e'

/** Журнал службы: из него берётся ссылка подтверждения почты (как в `smoke.sh`). */
export const SERVE_LOG = path.join(STAND_DIR, 'serve.log')

/** База стенда: в неё лезет проверка админки, чтобы выдать право руками. */
export const DB_FILE = path.join(STAND_DIR, 'koritsu.db')

/**
 * Каталог словаря. Тексты в проверках берутся ключами перевода, а не строками:
 * иначе правка одного слова в `ru/*.json` роняет десяток проверок.
 *
 * Путь считается от текущего каталога, а не от `__dirname`: `pnpm e2e`
 * запускается из `web/`, но проверку могут позвать и из корня репозитория.
 */
export const I18N_DIR = (() => {
  for (const кандидат of ['src/i18n/ru', 'web/src/i18n/ru']) {
    const полный = path.resolve(process.cwd(), кандидат)
    if (fs.existsSync(полный)) return полный
  }
  throw new Error(`не найден каталог словаря; запускать из web/ (сейчас ${process.cwd()})`)
})()

/**
 * Интерпретатор для служебных вставок проверок (шаблон DOCX, правка базы).
 * Берётся `PYTHON` из окружения (его ставит `web/e2e/stack.sh`), иначе venv
 * репозитория ищется тем же способом, что и словарь: `pnpm e2e` запускается из
 * `web/`, но проверку могут позвать и из корня. Абсолютного пути к чьей-то
 * машине здесь быть не должно — он уехал бы в репозиторий.
 */
export const PYTHON =
  process.env.PYTHON ??
  (() => {
    for (const кандидат of ['../.venv/bin/python', '.venv/bin/python']) {
      const полный = path.resolve(process.cwd(), кандидат)
      if (fs.existsSync(полный)) return полный
    }
    return 'python3'
  })()
