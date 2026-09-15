/**
 * draftJson — JSON черновика ↔ карточки для правки (`docs/cards-format.md`).
 *
 * **Источник правды — текст черновика.** Служба отдаёт черновик JSON-строкой
 * набора (`text`) и разобранным набором (`set`), но в наборе только годные
 * карточки. Правка поэтому идёт по тексту: из массива `cards` берутся все
 * элементы по порядку, включая отклонённые разбором, элемент правится, JSON
 * собирается заново и уходит целиком `PUT /api/cards/drafts/{id}`. Так
 * отклонённая карточка не пропадает молча при правке соседней, а номер карточки
 * в проблеме разбора (`problem.card`, с нуля) совпадает с индексом в массиве.
 *
 * **Разбирает служба.** Здесь нет ни санации, ни проверки потолков, ни
 * валидатора: чтение ровно такое, чтобы показать карточки полями и собрать JSON
 * обратно без потерь. Проблемы, которые видит человек, всегда серверные.
 *
 * **Сборка бережная.** Корневой объект файла хранится целиком (`head`), и при
 * сборке меняется только значение `cards` — на том же месте среди ключей.
 * Каждая карточка хранит свой исходный элемент (`raw`): правка переписывает в
 * нём `q`, `a`, `note`, `topic`, а `id` и неизвестные поля остаются как были.
 * Элемент массива, который не объект, тоже сохраняется как есть — его можно
 * удалить, но не править полями.
 */

/** Корневой объект файла набора: `format`, `title`, `defaults`, … и прочие поля как были. */
export type DraftHead = Record<string, unknown>

/** Карточка черновика для правки. */
export type DraftCard = {
  /**
   * Ключ строки на экране: `id` карточки, если он строка и в черновике не
   * повторяется, иначе `~<индекс>`. В файл не пишется.
   */
  key: string
  /** Индекс в массиве `cards` — тот же, что `problem.card`. */
  index: number
  /** `id` из файла; нет — `null`. */
  id: string | null
  /** Название темы; нет или пусто — `null`. */
  topic: string | null
  q: string
  a: string
  note: string | null
  /** Элемент массива — объект; иначе показывается сырым и не правится полями. */
  editable: boolean
  /** Исходный элемент массива со всеми полями. */
  raw: unknown
}

/** Разобранный черновик. */
export type DraftDoc = { head: DraftHead; cards: DraftCard[] }

/** Черновик нельзя разобрать: не JSON, корень не объект или `cards` не массив. */
export class DraftParseError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DraftParseError'
  }
}

/** Значение формата при записи. */
export const CARDS_FORMAT = 'koritsu.cards'
export const CARDS_FORMAT_VERSION = 1

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Поле строкой: строка как есть, пустое — пусто, прочее — его JSON. */
function text(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === undefined || value === null) return ''
  return JSON.stringify(value)
}

function optional(value: unknown): string | null {
  const s = text(value)
  return s.trim() ? s : null
}

function readCards(items: unknown[]): DraftCard[] {
  const ids = new Map<string, number>()
  for (const item of items) {
    if (isObject(item) && typeof item.id === 'string' && item.id) ids.set(item.id, (ids.get(item.id) ?? 0) + 1)
  }
  return items.map((item, index) => {
    if (!isObject(item)) {
      return { key: `~${index}`, index, id: null, topic: null, q: text(item), a: '', note: null, editable: false, raw: item }
    }
    const id = typeof item.id === 'string' && item.id ? item.id : null
    return {
      key: id && ids.get(id) === 1 ? id : `~${index}`,
      index,
      id,
      topic: optional(item.topic)?.trim() ?? null,
      q: text(item.q),
      a: text(item.a),
      note: optional(item.note),
      editable: true,
      raw: item,
    }
  })
}

/**
 * JSON-строка черновика → заголовок файла и все карточки по порядку массива.
 * Пустой текст — пустой черновик (агент ещё не записал ни одной части).
 * Бросает `DraftParseError`, если текст нельзя править без потерь.
 */
export function parseDraft(source: string): DraftDoc {
  const body = source.replace(/^\uFEFF/, '')
  if (!body.trim()) return { head: {}, cards: [] }
  let root: unknown
  try {
    root = JSON.parse(body)
  } catch (cause) {
    throw new DraftParseError(cause instanceof Error ? cause.message : String(cause))
  }
  if (!isObject(root)) throw new DraftParseError('root is not an object')
  const cards = root.cards
  if (cards !== undefined && !Array.isArray(cards)) throw new DraftParseError('cards is not an array')
  return { head: root, cards: readCards(cards ?? []) }
}

/**
 * Черновик в JSON с отступом 2. Ключи корня идут в исходном порядке, `cards` —
 * на своём месте; у нового файла впереди `format` и `version`.
 */
export function stringifyDraft(head: DraftHead, cards: DraftCard[]): string {
  const root: Record<string, unknown> = {}
  if (!('format' in head)) root.format = CARDS_FORMAT
  if (!('version' in head)) root.version = CARDS_FORMAT_VERSION
  Object.assign(root, head)
  // Присваивание существующему ключу не меняет его место среди ключей. Элементы
  // уходят исходными объектами: правка уже записана в `raw`, лишние поля — там же.
  root.cards = cards.map((card) => card.raw)
  return `${JSON.stringify(root, null, 2)}\n`
}

/** Правка карточки полями. Пустые `note` и `topic` убирают поле из элемента. */
export type CardFields = { q: string; a: string; note: string | null; topic: string | null }

/** Черновик с правленной карточкой (по ключу). */
export function withCard(doc: DraftDoc, key: string, patch: CardFields): DraftDoc {
  return {
    ...doc,
    cards: doc.cards.map((c) => {
      if (c.key !== key || !c.editable || !isObject(c.raw)) return c
      const raw: Record<string, unknown> = { ...c.raw, q: patch.q, a: patch.a }
      if (patch.note) raw.note = patch.note
      else delete raw.note
      if (patch.topic) raw.topic = patch.topic
      else delete raw.topic
      return { ...c, q: patch.q, a: patch.a, note: patch.note, topic: patch.topic, raw }
    }),
  }
}

/** Черновик без карточки; индексы остальных пересчитываются по новому массиву. */
export function withoutCard(doc: DraftDoc, key: string): DraftDoc {
  return { ...doc, cards: readCards(doc.cards.filter((c) => c.key !== key).map((c) => c.raw)) }
}

/** Названия тем в порядке первого появления. */
export function topicsOf(doc: DraftDoc): string[] {
  const seen = new Set<string>()
  for (const card of doc.cards) if (card.topic) seen.add(card.topic)
  return [...seen]
}

/** Карточки по темам: сначала без темы, затем темы в порядке первого появления. */
export function groupByTopic(doc: DraftDoc): { title: string | null; cards: DraftCard[] }[] {
  const groups: { title: string | null; cards: DraftCard[] }[] = []
  const loose = doc.cards.filter((c) => !c.topic)
  if (loose.length) groups.push({ title: null, cards: loose })
  const index = new Map<string, number>()
  for (const card of doc.cards) {
    if (!card.topic) continue
    let at = index.get(card.topic)
    if (at === undefined) {
      at = groups.push({ title: card.topic, cards: [] }) - 1
      index.set(card.topic, at)
    }
    groups[at]?.cards.push(card)
  }
  return groups
}

/** Строковое поле корня файла (`title`, `description`, `language`). */
export function headText(head: DraftHead, name: string): string {
  const value = head[name]
  return typeof value === 'string' ? value : ''
}
