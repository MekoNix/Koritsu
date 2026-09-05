/**
 * api/types — формы ответов, которых нет в документе OpenAPI.
 *
 * Часть обработчиков службы объявлена как `-> dict`, и FastAPI записывает в
 * схему честное «объект произвольной формы». Генератор превращает это в
 * `Record<string, unknown>`, и экран, которому нужен `me.email`, вынужден
 * приводить тип у себя — то есть описывать форму заново в каждом файле.
 *
 * Поэтому формы, нужные оболочке, описаны здесь **один раз**, рядом со ссылкой
 * на место в службе, откуда они берутся. Это не второй договор: договор один и
 * лежит в службе, здесь — его прочтение. Если служба поменяет форму, ломаться
 * должно в одном файле, а не в семи.
 *
 * Что делать агентам B–E: формы своих областей описывать так же — своим файлом
 * `features/<область>/types.ts`, не дописывая сюда.
 */

/**
 * `packages/api/accounts/routes.py: профиль()`.
 *
 * Внимание: `GET /api/auth/me` отдаёт это ВНУТРИ обёртки — `{"user": {…}}`.
 * Обёртку снимает `hooks/useMe.ts`, и снимать её больше нигде не надо.
 */
export type Me = {
  id: string
  email: string
  plan: string
  email_confirmed: boolean
  totp_enabled: boolean
  /** Признак админа. По нему и только по нему открывается `/admin`. */
  is_admin: boolean
  created_at: string
}

/** `packages/api/modules/__init__.py: ModuleInfo.to_dict()`. */
export type ModuleInfo = {
  id: string
  /** По-английски: перевод делает интерфейс (`shell.nav.<id>`). */
  title: string
  /** Префикс маршрутов модуля, например `/api/projects`. */
  routes: string
}

/** `packages/api/runs/limits.py: Расход.наружу()` + цены видов. */
export type Usage = {
  plan: string
  limit_units: number
  spent_units: number
  remaining_units: number
  /** ISO — первое число расчётного месяца. */
  period_start: string
  /** Цена одного задания каждого вида, во внутренних единицах. */
  prices: Record<string, number>
}

/** `packages/api/notifications/service.py: карточка()`. */
export type Notification = {
  id: string
  kind: string
  job_id: string | null
  data: Record<string, unknown>
  read_at: string | null
  created_at: string
}

/** Тело `GET /api/notifications`. */
export type NotificationsPage = {
  notifications: Notification[]
  unread_count: number
}

/** `packages/api/jobs/service.py: карточка_события()` — кадр потока задания. */
export type JobEvent = {
  seq: number
  kind: string
  data: Record<string, unknown>
  at: string
}

/** Конечные состояния задания (`packages/api/jobs/models.py: TERMINAL`). */
export const TERMINAL_STATUSES = ['done', 'failed', 'cancelled'] as const
export type JobStatus = 'queued' | 'running' | (typeof TERMINAL_STATUSES)[number]

export function isTerminal(status: string | undefined): boolean {
  return !!status && (TERMINAL_STATUSES as readonly string[]).includes(status)
}
