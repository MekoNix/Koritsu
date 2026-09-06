/**
 * i18n — один словарь, собранный из всех `ru/*.json`.
 *
 * **Зачем автоматическая сборка.** Один общий `ru.json` собирал бы правки со
 * всего сайта в один файл, и любые две одновременные правки расходились бы там
 * же. Поэтому у каждой области свой файл, а словарь склеивается из каталога
 * через `import.meta.glob`: чтобы завести перевод, достаточно положить
 * `src/i18n/ru/<область>.json`, и ничего больше править не надо.
 *
 * **Ключ = имя файла + путь внутри него.** `ru/shell.json` с `{"search": …}`
 * даёт `shell.search`. Префикс из имени файла, а не из содержимого: иначе два
 * файла однажды объявят один и тот же корень и затрут друг друга молча.
 *
 * **Голых русских строк в JSX нет.** Единственные исключения —
 * имена собственные (названия тем, шрифтов), они лежат рядом с данными.
 *
 * Язык один — русский. Обвязка на второй язык здесь не заводится: пока его
 * нет, она была бы описанием несуществующего.
 */

type Tree = { [k: string]: string | Tree }

/** Развернуть дерево в плоские ключи с точками. */
function flatten(tree: Tree, prefix: string, out: Record<string, string>): void {
  for (const [key, value] of Object.entries(tree)) {
    const full = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out[full] = value
    else flatten(value, full, out)
  }
}

const files = import.meta.glob<{ default: Tree }>('./ru/*.json', { eager: true })

export const dictionary: Record<string, string> = (() => {
  const out: Record<string, string> = {}
  for (const [path, module] of Object.entries(files)) {
    // './ru/shell.json' → 'shell'
    const area = path.slice(path.lastIndexOf('/') + 1).replace(/\.json$/, '')
    flatten(module.default, area, out)
  }
  return out
})()

/**
 * Перевод по ключу. Неизвестный ключ возвращается как есть — так пропажа видна
 * в интерфейсе сразу, а не превращается в пустое место.
 *
 * Подстановки — по имени: `t('usage.left', { n: 12 })` для `"Осталось {n}"`.
 */
export function t(key: string, vars?: Record<string, string | number>): string {
  const text = dictionary[key]
  if (text === undefined) {
    if (import.meta.env.DEV) console.warn(`[i18n] нет ключа: ${key}`)
    return key
  }
  if (!vars) return text
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  )
}

/**
 * Тот же `t`, но хуком — чтобы компоненты не импортировали функцию напрямую и
 * появление второго языка не потребовало переписывать каждый вызов.
 */
export function useT(): typeof t {
  return t
}
