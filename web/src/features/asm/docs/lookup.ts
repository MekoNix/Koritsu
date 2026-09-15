/**
 * lookup — поиск записи справки по токену из кода и по строке поиска.
 *
 * Все функции принимают набор записей: у TASM и у MinGW x64 справки разные, и
 * `mov` в одном режиме ведёт в запись TASM, в другом — в запись x86-64. Индекс
 * псевдонимов строится один раз на набор и держится, пока жив сам массив.
 *
 * `lookup` понимает то, что попадается под курсором в исходнике, листинге и
 * регистрах: мнемоники (`loopne`), регистры и их половинки (`cl`), флаги и их
 * мнемоники DebugX (`ZF`, `ZR`), функции прерываний в любой из привычных
 * записей (`int 21h`, `21h/09h`, `int 21h, 0Ah`, `ah=4Ch`), директивы
 * (`.model`, `@data`, `.quad`) и целые операнды (`byte ptr [bx]`, `rep movsb`,
 * `[bx+si]`, `qword ptr [rsp+32]`) — для последних берётся первое узнанное
 * слово. Записи GAS находятся и в записи AT&T: `%rax` → `rax`, `movq` → `mov`,
 * `-8(%rbp)` → `rbp`; вызов из трассы `kernel32.WriteFile` и ячейка импорта
 * `__imp_WriteFile` — по имени функции.
 *
 * Псевдоним принадлежит первой записи, которая его объявила: порядок записей в
 * наборе решает, что `di` — регистр, а не мнемоника флага IF.
 */
import { DOC_SECTIONS, SECTION_TITLE, type DocEntry, type DocSection } from './entries'

interface DocIndex {
  alias: Map<string, string>
  byId: Record<string, DocEntry>
}

const INDEX = new WeakMap<readonly DocEntry[], DocIndex>()

function indexOf(entries: readonly DocEntry[]): DocIndex {
  let ix = INDEX.get(entries)
  if (!ix) {
    const alias = new Map<string, string>()
    const byId: Record<string, DocEntry> = {}
    for (const e of entries) {
      byId[e.id] = e
      for (const k of [e.id, e.name.toLowerCase(), ...e.alias.map((a) => a.toLowerCase())]) {
        if (!alias.has(k)) alias.set(k, e.id)
      }
    }
    ix = { alias, byId }
    INDEX.set(entries, ix)
  }
  return ix
}

/** Запись по идентификатору; `null` — такой в наборе нет. */
export function entryById(id: string | null | undefined, entries: readonly DocEntry[]): DocEntry | null {
  return id ? (indexOf(entries).byId[id] ?? null) : null
}

/** Разделы, в которых у набора есть записи, в порядке показа. */
export function sectionsOf(entries: readonly DocEntry[]): readonly { id: DocSection; title: string }[] {
  const present = new Set(entries.map((e) => e.sec))
  return DOC_SECTIONS.filter((s) => present.has(s.id))
}

/** Нижний регистр, пробелы схлопнуты. */
export function normToken(token: string | null | undefined): string {
  return String(token ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
}

const pad = (h: string) => (h.length < 2 ? `0${h}` : h)

/** Слово кода → псевдоним: снять `%` регистра AT&T, суффикс размера (`addq`), обвязку имени функции. */
function wordId(word: string, alias: Map<string, string>): string | null {
  const w = word.replace(/^%/, '')
  if (!w) return null
  const direct = alias.get(w)
  if (direct) return direct
  // kernel32.writefile · __imp_writefile
  const fn = w.replace(/^.*\./, '').replace(/^_*imp_+/, '').replace(/@.*$/, '')
  if (fn !== w) {
    const id = alias.get(fn)
    if (id) return id
  }
  if (/^[a-z]+[bwlq]$/.test(w)) return alias.get(w.slice(0, -1)) ?? null
  return null
}

/** Идентификатор записи набора по токену; `null` — ничего подходящего. */
export function lookup(token: string | null | undefined, entries: readonly DocEntry[]): string | null {
  const t = normToken(token)
  if (!t) return null
  const { alias, byId } = indexOf(entries)
  if (byId[t]) return t
  const direct = alias.get(t)
  if (direct) return direct

  // int 21h 09h · 21h/09h · 21h:9 · int 10h, 0Eh · 21h ah=4Ch
  let m = t.match(/^(?:int ?)?(21|10|16)h?(?: ?[/:,.] ?| |)(?:ah ?= ?)?([0-9a-f]{1,2})h?$/)
  if (m) {
    const int = m[1] ?? ''
    const fn = pad(m[2] ?? '')
    const id = int === '21' ? `dos-${fn}` : `bios-${int}-${fn}`
    if (byId[id]) return id
  }
  m = t.match(/^ah ?= ?([0-9a-f]{1,2})h?$/)
  if (m) {
    const id = `dos-${pad(m[1] ?? '')}`
    if (byId[id]) return id
  }
  // У BIOS без номера функции — самая ходовая функция прерывания.
  m = t.match(/^int ?(10|16)h?$/)
  if (m) {
    const id = m[1] === '10' ? 'bios-10-0e' : 'bios-16-00'
    if (byId[id]) return id
  }

  const clean = t
    .replace(/[[\](),:+*$]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  const whole = alias.get(clean)
  if (whole) return whole
  for (const word of clean.split(' ')) {
    const id = wordId(word, alias)
    if (id) return id
  }
  return null
}

/** Запись набора по идентификатору или по токену. */
export function findEntry(token: string | null | undefined, entries: readonly DocEntry[]): DocEntry | null {
  if (!token) return null
  const byId = entryById(token, entries)
  if (byId) return byId
  return entryById(lookup(token, entries), entries)
}

/** «См. также» записи: без неё самой и без повторов, в порядке объявления. */
export function seeAlso(entry: DocEntry, entries: readonly DocEntry[]): DocEntry[] {
  const out: DocEntry[] = []
  for (const token of entry.see) {
    const e = findEntry(token, entries)
    if (e && e.id !== entry.id && !out.includes(e)) out.push(e)
  }
  return out
}

const HAY = new WeakMap<DocEntry, string>()

function haystack(e: DocEntry): string {
  let h = HAY.get(e)
  if (h === undefined) {
    h = [e.name, e.alias.join(' '), e.short, e.kw, e.syntax ?? '', e.desc, SECTION_TITLE[e.sec]]
      .join(' ')
      .toLowerCase()
    HAY.set(e, h)
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

/** Записи набора в разделе под строку поиска; пустой запрос — все записи раздела по порядку. */
export function searchEntries(query: string, sec: DocSection | 'all', entries: readonly DocEntry[]): DocEntry[] {
  const q = normToken(query)
  const pool = entries.filter((e) => sec === 'all' || e.sec === sec)
  if (!q) return pool
  const words = q.split(' ')
  return pool
    .map((e, i) => ({ e, s: score(e, words, q), i }))
    .filter((x) => x.s >= 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.e)
}
