/**
 * format — мелкие приведения к человеческому виду, общие для дашборда и
 * проектов.
 *
 * Подписи единиц лежат в переводах (`projects.unit.*`), а не строками здесь:
 * правило: голых русских строк в коде нет. Поэтому функции берут `t`
 * первым аргументом, а не зовут его сами: так их можно проверить тестом, не
 * поднимая словарь.
 */

/** Ступени размера. Ключи переводов — `projects.size.b|kb|mb|gb`. */
const STEPS = ['b', 'kb', 'mb', 'gb'] as const

/**
 * Байты человеку: «36,6 КБ». Знак после запятой — только там, где он что-то
 * значит: «1,2 МБ» полезно, «1234,0 Б» — шум.
 */
export function formatBytes(
  t: (key: string, vars?: Record<string, string | number>) => string,
  bytes: number,
): string {
  let value = Math.max(0, bytes)
  let step = 0
  while (value >= 1024 && step < STEPS.length - 1) {
    value /= 1024
    step += 1
  }
  const digits = step === 0 || value >= 100 ? 0 : 1
  return t(`projects.size.${STEPS[step]}`, {
    n: value.toLocaleString('ru-RU', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }),
  })
}

/**
 * Дата изменения коротким видом: время — сегодняшнему, «4 сентября» — этому
 * году, «4 сентября 2025» — прошлому. Часы у прошлогоднего файла не значат
 * ничего, а место занимают.
 */
export function formatWhen(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return ''
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const sameDay =
    at.getFullYear() === now.getFullYear() &&
    at.getMonth() === now.getMonth() &&
    at.getDate() === now.getDate()
  if (sameDay) return at.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  const sameYear = at.getFullYear() === now.getFullYear()
  return at.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: sameYear ? undefined : 'numeric',
  })
}

/**
 * Русское склонение при числе: «1 работа», «2 работы», «5 работ».
 * Формы приходят готовой тройкой из переводов — правило одно на язык, а не на
 * каждое слово.
 */
export function plural(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(n) % 100
  const last = abs % 10
  if (abs > 10 && abs < 20) return forms[2]
  if (last > 1 && last < 5) return forms[1]
  if (last === 1) return forms[0]
  return forms[2]
}

/**
 * Расширение файла для значка карточки: «отчёт.docx» → «DOCX». Служба
 * присылает и свой `kind` (`pdf`, `docx`, `code`), но у кода расширение
 * говорит больше: `.py` и `.cpp` — оба `code`.
 */
export function fileExt(name: string): string {
  const dot = name.lastIndexOf('.')
  if (dot <= 0 || dot === name.length - 1) return ''
  return name
    .slice(dot + 1)
    .toUpperCase()
    .slice(0, 5)
}
