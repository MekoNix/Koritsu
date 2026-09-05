/**
 * types — формы ответов админки. Служба объявляет их как `-> dict`, поэтому в
 * OpenAPI у них «объект произвольной формы»; здесь их прочтение, со ссылкой на
 * место в службе.
 */

/** `packages/api/admin/service.py: карточка_человека()`. */
export type AdminUser = {
  id: string
  email: string
  /** Ник: имя человека на экране. */
  nickname: string
  plan: string
  is_admin: boolean
  /** Личные лимиты поверх плановых. Пусто — берутся значения плана. */
  limits: Record<string, unknown>
  quota_bytes: number
  bytes_used: number
  /** Расход за календарный месяц во внутренних единицах. */
  spent_units: number
  email_confirmed: boolean
  created_at: string | null
  /** Аккаунт удалён (мягко) — человек убрал себя сам. */
  deleted_at: string | null
  /**
   * Аккаунт заблокирован администратором службы. Не то же, что `deleted_at`, и
   * не то же, что замок за перебор пароля: этот снимает только администратор.
   */
  blocked_at: string | null
}

/** Тело `GET /api/admin/users`. */
export type AdminUsersPage = { users: AdminUser[] }

/** `packages/api/admin/service.py: очередь()`. */
export type AdminQueue = {
  queued: number
  running: number
  by_kind: Record<string, { queued: number; running: number }>
  slots: { per_machine: number; per_user: number }
  workers: {
    worker_id: string | null
    job_id: string
    kind: string
    /** Сколько секунд назад воркер бился. `null` — не бился ни разу. */
    heartbeat_age_s: number | null
  }[]
  /** Через сколько секунд без сердцебиения воркер считается потерянным. */
  lost_after_s: number
}

/** `packages/api/admin/service.py: карточка_события()`. */
export type SecurityEvent = {
  id: string
  user_id: string | null
  ip: string
  kind: string
  detail: Record<string, unknown>
  created_at: string | null
}

/** Тело `GET /api/admin/security`. */
export type SecurityEventsPage = { events: SecurityEvent[] }

/** Точка ряда по дням из `GET /api/admin/stats`. */
export type StatsDay = { day: string; units: number }

/** Точка ряда регистраций. Поле другое, поэтому и тип другой. */
export type StatsRegistration = { day: string; count: number }

/** Задания периода одного вида: сколько всего и сколько упало. */
export type StatsKind = { kind: string; count: number; failed: number }

/** `packages/api/admin/service.py: сводка()` — ряды для графиков «Обзора». */
export type AdminStats = {
  /** Сколько дней в ряду. Ряд плотный: дни идут подряд, включая пустые. */
  days: number
  /** Начало периода, 00:00 UTC первого дня. */
  since: string
  usage_by_day: StatsDay[]
  jobs_by_kind: StatsKind[]
  registrations_by_day: StatsRegistration[]
  /** Сколько людей запускало за период хоть что-то (не «сколько заведено»). */
  active_users: number
}

/** Тело `PATCH /api/admin/users/{user_id}` (`UserPatchIn`). */
export type UserPatch = {
  /** Только имя из справочника (`GET /api/admin/plans`); иное — `unknown_plan`. */
  plan?: string
  is_admin?: boolean
  /** Заменяются целиком: не заданное поле — не «оставить», а «убрать». */
  limits?: Record<string, number>
  /** Заблокировать или разблокировать. Блокировка отзывает все сессии. */
  blocked?: boolean
}

/** Строка справочника планов: `packages/api/runs/limits.py: справочник()`. */
export type AdminPlan = {
  plan: string
  /** Месячный потолок расхода во внутренних единицах. */
  monthly_units: number
  /** Квота места на томе, байт. */
  quota_bytes: number
}

/** Тело `GET /api/admin/plans`. */
export type AdminPlansPage = { plans: AdminPlan[] }

/** Тело `POST /api/admin/users` (`UserCreateIn`). */
export type UserCreate = {
  email: string
  plan?: string
  /** Не названный — берётся из почты службой. */
  nickname?: string
}

/**
 * Ответ `POST /api/admin/users`: карточка и ссылка сброса.
 *
 * `reset_url` показывается **один раз**: открытой её служба нигде не хранит
 * (в базе только sha256), и второго способа её увидеть нет — как у строки
 * ключа для скриптов.
 */
export type CreatedUser = { user: AdminUser; reset_url: string }
