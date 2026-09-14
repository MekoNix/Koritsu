/**
 * lookup — поиск записи справки по токену из кода и по строке поиска.
 *
 * `lookup` понимает то, что попадается под курсором в исходнике, листинге и
 * регистрах: мнемоники (`loopne`), регистры и их половинки (`cl`), флаги и их
 * мнемоники DebugX (`ZF`, `ZR`), функции прерываний в любой из привычных
 * записей (`int 21h`, `21h/09h`, `int 21h, 0Ah`, `ah=4Ch`), директивы
 * (`.model`, `@data`) и целые операнды (`byte ptr [bx]`, `rep movsb`,
 * `[bx+si]`) — для последних берётся первое узнанное слово.
 *
 * Псевдоним принадлежит первой записи, которая его объявила: порядок записей в
 * `entries.ts` решает, что `di` — регистр, а не мнемоника флага IF.
 */
import { DOC_BY_ID, DOC_ENTRIES, SECTION_TITLE, type DocEntry, type DocSection } from './entries'

const ALIAS = new Map<string, string>()
for (const e of DOC_ENTRIES) {
  for (const k of [e.id, e.name.toLowerCase(), ...e.alias.map((a) => a.toLowerCase())]) {
    if (!ALIAS.has(k)) ALIAS.set(k, e.id)
  }
}

/** Нижний регистр, пробелы схлопнуты. */
export function normToken(token: string | null | undefined): string {
  return String(token ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
}

const pad = (h: string) => (h.length < 2 ? `0${h}` : h)

/** Идентификатор записи по токену; `null` — ничего подходящего. */
export function lookup(token: string | null | undefined): string | null {
  const t = normToken(token)
  if (!t) return null
  if (DOC_BY_ID[t]) return t
  const direct = ALIAS.get(t)
  if (direct) return direct

  // int 21h 09h · 21h/09h · 21h:9 · int 10h, 0Eh · 21h ah=4Ch
  let m = t.match(/^(?:int ?)?(21|10|16)h?(?: ?[/:,.] ?| |)(?:ah ?= ?)?([0-9a-f]{1,2})h?$/)
  if (m) {
    const int = m[1] ?? ''
    const fn = pad(m[2] ?? '')
    const id = int === '21' ? `dos-${fn}` : `bios-${int}-${fn}`
    if (DOC_BY_ID[id]) return id
  }
  m = t.match(/^ah ?= ?([0-9a-f]{1,2})h?$/)
  if (m) {
    const id = `dos-${pad(m[1] ?? '')}`
    if (DOC_BY_ID[id]) return id
  }
  // У BIOS без номера функции — самая ходовая функция прерывания.
  m = t.match(/^int ?(10|16)h?$/)
  if (m) return m[1] === '10' ? 'bios-10-0e' : 'bios-16-00'

  const clean = t
    .replace(/[[\],:+]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  const whole = ALIAS.get(clean)
  if (whole) return whole
  for (const word of clean.split(' ')) {
    const id = ALIAS.get(word)
    if (id) return id
  }
  return null
}

/** Запись по идентификатору или по токену. */
export function findEntry(token: string | null | undefined): DocEntry | null {
  if (!token) return null
  const byId = DOC_BY_ID[token]
  if (byId) return byId
  const id = lookup(token)
  return id ? (DOC_BY_ID[id] ?? null) : null
}

/** «См. также» записи: без неё самой и без повторов, в порядке объявления. */
export function seeAlso(entry: DocEntry): DocEntry[] {
  const out: DocEntry[] = []
  for (const token of entry.see) {
    const e = findEntry(token)
    if (e && e.id !== entry.id && !out.includes(e)) out.push(e)
  }
  return out
}

const HAY = new Map<string, string>()

function haystack(e: DocEntry): string {
  let h = HAY.get(e.id)
  if (h === undefined) {
    h = [e.name, e.alias.join(' '), e.short, e.kw, e.syntax ?? '', e.desc, SECTION_TITLE[e.sec]]
      .join(' ')
      .toLowerCase()
    HAY.set(e.id, h)
  }
  return h
}

/**
 * Вес записи для строки поиска; `-1` — не подходит.
 *
 * Подходит запись, в тексте которой есть все слова запроса. Выше всего —
 * точное имя, затем имя с этого начала, затем совпадение в короткой строке:
 * набравший `div` ждёт первой команду, а не десяток статей, где она упомянута.
 */
function score(e: DocEntry, words: string[], q: string): number {
  const name = e.name.toLowerCase()
  let s = 0
  if (e.alias.includes(q) || name === q) s += 100
  else if (e.alias.some((a) => a.startsWith(q)) || name.startsWith(q)) s += 60
  if (e.short.toLowerCase().includes(q)) s += 30
  const h = haystack(e)
  for (const w of words) if (!h.includes(w)) return -1
  return s + 1
}

/** Записи раздела под строку поиска; пустой запрос — все записи раздела по порядку. */
export function searchEntries(query: string, sec: DocSection | 'all'): DocEntry[] {
  const q = normToken(query)
  const pool = DOC_ENTRIES.filter((e) => sec === 'all' || e.sec === sec)
  if (!q) return pool
  const words = q.split(' ')
  return pool
    .map((e, i) => ({ e, s: score(e, words, q), i }))
    .filter((x) => x.s >= 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.e)
}
