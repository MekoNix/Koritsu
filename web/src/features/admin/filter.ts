/**
 * filter — поиск и страницы по списку людей.
 *
 * Считается на сайте, потому что служба этого не умеет: `GET /api/admin/users`
 * знает один параметр `limit` и отдаёт всех новыми сверху. Вынесено отдельным
 * файлом без React намеренно — это чистые функции, и проверяются они тестом
 * без единого отрисованного компонента.
 */
import type { AdminUser } from './types'

/** Сколько строк на странице. Больше двадцати таблица перестаёт помещаться. */
export const PAGE_SIZE = 20

/**
 * Отбор по строке поиска: почта или идентификатор, без учёта регистра.
 * Пустая строка — весь список (а не пустой), иначе первый же заход в раздел
 * встречал бы человека словами «никого не нашлось».
 */
export function filterUsers(users: readonly AdminUser[], query: string): AdminUser[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return [...users]
  return users.filter(
    (user) => user.email.toLowerCase().includes(needle) || user.id.toLowerCase().includes(needle),
  )
}

/** Сколько страниц выйдет. Пустой список — одна страница, а не ноль. */
export function pageCount(total: number, size: number = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / size))
}

/**
 * Одна страница списка. Номер приводится в границы, а не считается верным:
 * страница 5 после сужения поиска до одной строки — обычное дело, и падать
 * или показывать пустоту здесь нельзя.
 */
export function pageOf<T>(items: readonly T[], page: number, size: number = PAGE_SIZE): T[] {
  const last = pageCount(items.length, size)
  const safe = Math.min(Math.max(1, Math.trunc(page) || 1), last)
  return items.slice((safe - 1) * size, safe * size)
}

/** Сколько человек с правом админа. Для подписи под таблицей. */
export function countAdmins(users: readonly AdminUser[]): number {
  return users.reduce((sum, user) => sum + (user.is_admin ? 1 : 0), 0)
}
