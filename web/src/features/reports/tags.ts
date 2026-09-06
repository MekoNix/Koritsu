/**
 * tags — счёт по тегам, чтение и запись значения. Чистые функции, без React.
 *
 * Отдельным файлом, потому что это единственная арифметика области, и её надо
 * проверять тестом, а не глазами по экрану: прогресс «7 из 12» — первое, на что
 * человек смотрит, и первое, что молча врёт, если считать заполненность
 * по-разному в списке слева и в шапке над ним.
 */
import type { ProjectTag, TagValue } from './types'

/** Типы значений, которые человек правит как текст (`hokoku.wire._TYPES`). */
const ТЕКСТОВЫЕ = new Set(['text', 'markdown', 'code'])

/** Поля значения, в которых лежит текст. Порядок — как у службы (`fill_tag._текстом`). */
const ПОЛЯ_ТЕКСТА = ['text', 'markdown', 'code'] as const

export type TagSummary = {
  total: number
  filled: number
  /** Заполнено моделью — то, что спецификация требует отличать от своего. */
  byAgent: number
  /** Написано рукой человека. */
  manual: number
  empty: number
  /** Доля заполненных, 0…100. Тегов нет — ноль, а не деление на ноль. */
  percent: number
}

/**
 * Сводка по тегам: сколько всего, сколько заполнено и кем.
 *
 * Считается по `filled` службы, а не по «в значениях есть ключ»: пустая строка,
 * записанная человеком, — это заполненный тег (у него есть версия и история), и
 * счёт, который считает её пустой, разойдётся с тем, что видно в списке.
 */
export function summarize(tags: ProjectTag[] | undefined): TagSummary {
  const список = tags ?? []
  const total = список.length
  const filled = список.filter((t) => t.filled).length
  const byAgent = список.filter((t) => t.filled && t.source === 'agent').length
  return {
    total,
    filled,
    byAgent,
    manual: filled - byAgent,
    empty: total - filled,
    percent: total === 0 ? 0 : Math.round((filled / total) * 100),
  }
}

/** Ключи незаполненных тегов, в порядке шаблона — то, что уедет в «сгенерировать всё». */
export function emptyKeys(tags: ProjectTag[] | undefined): string[] {
  return (tags ?? []).filter((t) => !t.filled).map((t) => t.key)
}

export type TagFilter = 'all' | 'empty' | 'filled' | 'agent'

/**
 * Отбор тегов поиском и фильтром. Ищется и по ключу, и по метке: человек
 * помнит либо `{{цель_работы}}`, либо «Цель работы», и заставлять его помнить
 * ровно одно из двух незачем.
 */
export function filterTags(
  tags: ProjectTag[] | undefined,
  query: string,
  filter: TagFilter,
): ProjectTag[] {
  const запрос = query.trim().toLowerCase()
  return (tags ?? []).filter((t) => {
    if (filter === 'empty' && t.filled) return false
    if (filter === 'filled' && !t.filled) return false
    if (filter === 'agent' && t.source !== 'agent') return false
    if (!запрос) return true
    return `${t.key} ${t.label}`.toLowerCase().includes(запрос)
  })
}

/**
 * Правится ли значение этого типа как текст.
 *
 * Прочие (таблица, картинка, схема, формула, оглавление) правятся JSON'ом в
 * `JsonEditor` с проверкой формы `values.validateValue`.
 */
export function isTextual(type: string | undefined): boolean {
  return ТЕКСТОВЫЕ.has(String(type ?? ''))
}

/**
 * Значение → то, что показывают человеку.
 *
 * Повторяет `runs/handlers/fill_tag._текстом`: у текстовых типов это сам текст,
 * у прочих — JSON, потому что «таблица словами» это не текст, а выдумка.
 * Значения нет — пустая строка: пустой тег выглядит просто пустым (бриф).
 */
export function valueText(value: TagValue | undefined | null): string {
  if (!value || typeof value !== 'object') return ''
  for (const поле of ПОЛЯ_ТЕКСТА) {
    const текст = value[поле]
    if (typeof текст === 'string') return текст
  }
  return JSON.stringify(value, null, 2)
}

/**
 * Текст → значение для записи.
 *
 * Прежнее значение берётся основой, чтобы правка текста не стирала соседние
 * поля (`lang` у кода, `caption` у листинга): служба пишет значение целиком,
 * и отправить один `text` значит потерять всё остальное.
 */
export function textToValue(
  text: string,
  { type, previous }: { type: string; previous?: TagValue | null },
): TagValue {
  const тип = previous?.type ?? type ?? 'markdown'
  return { ...(previous ?? {}), type: тип, text }
}

/** Название тега для человека: метка из шаблона, а нет её — сам ключ. */
export function tagTitle(tag: ProjectTag | undefined): string {
  if (!tag) return ''
  return tag.label.trim() || tag.key
}

/**
 * Две строки тега в списке: чем он назван и как называется ключ.
 *
 * Наверху — описание, то есть текст после двоеточия в `{{ключ:описание}}`
 * (служба отдаёт его полем `label`), внизу — сам ключ **без** фигурных скобок.
 * Читают список глазами человека, а не сборщика: «Цель работы» отвечает на
 * вопрос «что здесь пишется», а `{{цель_работы}}` — только на вопрос «как это
 * зовётся в бланке», и первым он быть не должен. Скобки при этом лишние: они
 * нужны в бланке, где текст надо отличить от подстановки, а в списке одних
 * подстановок отличать не от чего.
 *
 * Описания нет — одна строка, сам ключ: выдумывать описание из ключа значило бы
 * показывать человеку то, чего в бланке не написано.
 */
export function tagLines(tag: ProjectTag): { title: string; key: string | null } {
  const описание = tag.label.trim()
  return описание ? { title: описание, key: tag.key } : { title: tag.key, key: null }
}
