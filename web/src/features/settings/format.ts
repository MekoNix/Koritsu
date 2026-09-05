/**
 * format — как показывать числа и даты в настройках и в админке.
 *
 * Отдельным файлом, а не рядом с компонентами, по двум причинам. Первая
 * техническая: файл с компонентом, экспортирующий ещё и функцию, ломает
 * горячую перезагрузку React (`react-refresh/only-export-components`), а
 * `--max-warnings 0` превращает это в упавшую проверку. Вторая по сути: эти
 * четыре функции — единственное место, где решается, как выглядит дата и
 * сколько разрядов у числа, и два таких места разошлись бы.
 *
 * Язык один — русский, поэтому `ru-RU` записан явно, а не берётся из браузера:
 * иначе на английской системе даты в интерфейсе поехали бы в чужой формат.
 */

/** Дата: «4 сентября 2026». Часовой пояс браузерный — своего служба не хранит. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return '—'
  return at.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

/** Дата и время до секунд: «04.09, 21:07:48» — для журнала событий. */
export function formatMoment(iso: string | null | undefined): string {
  if (!iso) return '—'
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return '—'
  return at.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** Число с разрядами: 1 280 000 читается, 1280000 — нет. */
export function formatUnits(value: number): string {
  return new Intl.NumberFormat('ru-RU').format(value)
}

/**
 * Байты в человеческий вид. Тысяча, а не 1024: квота в службе задана в байтах
 * и объявляется человеку круглыми числами («5 ГБ»), а деление на 1024 дало бы
 * из ровных пяти гигабайт «4,7».
 */
export function formatBytes(bytes: number): string {
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']
  let value = Math.max(0, bytes)
  let index = 0
  while (value >= 1000 && index < units.length - 1) {
    value /= 1000
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}
