/**
 * table — сортировка таблиц админки, выгрузка в CSV и разбор по планам.
 *
 * Всё это считает сайт, а не служба, и по той же причине, что поиск в
 * `filter.ts`: `GET /api/admin/users` знает один параметр `limit` и отдаёт
 * список одним куском. Просить у неё `?sort=plan` значило бы получить
 * несортированный список под видом сортированного.
 *
 * Файл без React намеренно: это чистые функции, и проверяются они тестом без
 * единого отрисованного компонента (`table.test.ts`).
 */
import type { AdminUser } from './types'

/** Куда сортировать. Третье состояние — не значение, а отсутствие
 *  сортировки: см. `SortState` и `nextSort`. */
export type SortDir = 'asc' | 'desc'

/** Значение, по которому сравниваются строки. `null` — «пусто». */
export type SortValue = string | number | boolean | null | undefined

/**
 * Устойчивая сортировка по одному ключу.
 *
 * Устойчивая — то есть равные значения остаются в прежнем порядке: список
 * приходит от службы новыми сверху, и сортировка по плану обязана сохранить
 * внутри плана этот порядок, иначе строки прыгают при каждом перерисовывании.
 * `Array.prototype.sort` устойчив по стандарту с ES2019, поэтому своего
 * счётчика здесь нет.
 *
 * Пустые значения (`null`, `undefined`, пустая строка) всегда внизу — в обе
 * стороны. Человек, сортирующий по дате, ищет самые старые записи, а не
 * строки, у которых даты нет вовсе.
 */
export function sortRows<T>(rows: readonly T[], value: (row: T) => SortValue, dir: SortDir): T[] {
  const знак = dir === 'asc' ? 1 : -1
  const пусто = (v: SortValue) => v === null || v === undefined || v === ''
  return [...rows].sort((а, б) => {
    const va = value(а)
    const vb = value(б)
    if (пусто(va) && пусто(vb)) return 0
    if (пусто(va)) return 1
    if (пусто(vb)) return -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * знак
    return String(va).localeCompare(String(vb), 'ru') * знак
  })
}

/** Что сейчас отсортировано. `null` — порядок, в котором отдала служба. */
export type SortState<C extends string> = { col: C; dir: SortDir } | null

/**
 * Следующее состояние сортировки по щелчку. Первый щелчок — по возрастанию,
 * второй — по убыванию, третий снимает сортировку и возвращает порядок службы.
 * Третье состояние есть намеренно: без него вернуться к «как отдала служба»
 * можно только перезагрузкой страницы.
 */
export function nextSort<C extends string>(state: SortState<C>, col: C): SortState<C> {
  if (state?.col !== col) return { col, dir: 'asc' }
  if (state.dir === 'asc') return { col, dir: 'desc' }
  return null
}

/**
 * Поле CSV по RFC 4180: кавычки удваиваются, а поле берётся в кавычки, если в
 * нём есть разделитель, кавычка или перевод строки.
 *
 * Отдельно — ведущие `=`, `+`, `-`, `@`: Excel считает такое поле формулой и
 * выполняет её при открытии файла. Почта вида `=cmd|…` в выгрузке админки —
 * это не выдумка, а известная дыра (CSV injection), и закрывается она здесь,
 * а не памяткой не открывать выгрузки.
 */
export function csvField(значение: unknown): string {
  let текст = значение === null || значение === undefined ? '' : String(значение)
  if (/^[=+\-@\t\r]/.test(текст)) текст = `'${текст}`
  return /[",;\n\r]/.test(текст) ? `"${текст.replace(/"/g, '""')}"` : текст
}

/**
 * Таблица в CSV. Разделитель — точка с запятой: русский Excel считает запятую
 * десятичной, и файл с запятыми открывается у него одним столбцом.
 * Конец строки — CRLF, как требует тот же RFC.
 */
export function toCsv(headers: readonly string[], rows: readonly unknown[][]): string {
  return [headers, ...rows].map((строка) => строка.map(csvField).join(';')).join('\r\n')
}

/**
 * Отдать CSV браузеру файлом. С BOM: без него Excel читает UTF-8 как cp1251 и
 * показывает вместо русских заголовков кракозябры.
 *
 * Ссылка заводится и убирается тут же — оставлять `objectURL` живым значит
 * держать содержимое файла в памяти вкладки до её закрытия.
 */
export function downloadCsv(name: string, csv: string): void {
  // BOM записан кодом, а не самим знаком: невидимый символ в исходнике —
  // это правка, которую нельзя увидеть при чтении (и `no-irregular-whitespace`
  // ругается на него не зря).
  const кусок = new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' })
  const адрес = URL.createObjectURL(кусок)
  const ссылка = document.createElement('a')
  ссылка.href = адрес
  ссылка.download = name
  document.body.appendChild(ссылка)
  ссылка.click()
  ссылка.remove()
  URL.revokeObjectURL(адрес)
}

/** Строка вкладки «Планы»: сколько людей на плане и сколько они потратили. */
export type PlanRow = {
  plan: string
  count: number
  admins: number
  spent: number
}

/**
 * Разбор людей по планам.
 *
 * Справочника планов у службы нет: `PATCH /api/admin/users/{id}` принимает
 * `plan` свободной строкой до 32 символов, и списка «какие планы бывают» не
 * существует нигде. Поэтому таблица планов — это не справочник, а то, что
 * получилось: столько планов, сколько разных строк вписано людям. Опечатка
 * («pro » с пробелом) видна здесь отдельной строкой, и это скорее польза:
 * иначе её не видно вовсе.
 *
 * Удалённые люди считаются наравне: план у них остался, и владелец, глядящий
 * на разбор, ищет «кому что выдано», а не «кто сейчас ходит».
 */
export function planCounts(users: readonly AdminUser[]): PlanRow[] {
  const собрано = new Map<string, PlanRow>()
  for (const человек of users) {
    const план = человек.plan || '—'
    const строка = собрано.get(план) ?? { plan: план, count: 0, admins: 0, spent: 0 }
    строка.count += 1
    строка.admins += человек.is_admin ? 1 : 0
    строка.spent += человек.spent_units
    собрано.set(план, строка)
  }
  return [...собрано.values()].sort(
    (а, б) => б.count - а.count || а.plan.localeCompare(б.plan, 'ru'),
  )
}

/** Отбор по плану. Пустая строка — все планы, а не «план равен пустому». */
export function filterByPlan(users: readonly AdminUser[], plan: string): AdminUser[] {
  return plan ? users.filter((человек) => (человек.plan || '—') === plan) : [...users]
}
