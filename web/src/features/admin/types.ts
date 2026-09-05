/**
 * types — формы ответов админки. Служба объявляет их как `-> dict`, поэтому в
 * OpenAPI у них «объект произвольной формы»; здесь их прочтение, со ссылкой на
 * место в службе.
 */

/** `packages/api/admin/service.py: карточка_человека()`. */
export type AdminUser = {
  id: string
  email: string
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
  /** Аккаунт удалён (мягко). Своей «блокировки» у службы нет. */
  deleted_at: string | null
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
  plan?: string
  is_admin?: boolean
  /** Заменяются целиком: не заданное поле — не «оставить», а «убрать». */
  limits?: Record<string, number>
}
