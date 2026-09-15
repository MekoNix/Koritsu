/**
 * CardEditor — правка одной карточки черновика: вопрос, ответ, разбор, тема.
 *
 * На компьютере редактор стоит на месте строки карточки; на телефоне — во весь
 * экран, с «Отмена» и «Сохранить» вверху и полями, растянутыми на высоту: три
 * поля в строке списка на узком экране не помещаются, а клавиатура закрывает
 * половину того, что осталось.
 *
 * Поля — те же строки, что в JSON набора (`q`, `a`, `note`, `topic`), с
 * Markdown и формулами внутри. Экранировать ничего не нужно: JSON собирает
 * черновик. Тема выбирается из тем черновика или вписывается новая; пустое
 * поле — карточка без темы. Сохранение уходит наверх готовой правкой: черновик
 * пересобирает JSON целиком и отдаёт его службе.
 */
import { useId, useState } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Field, Input, Textarea } from '@/ui'

import type { CardFields, DraftCard } from './draftJson'

export type CardPatch = CardFields

export function CardEditor({
  card,
  topics,
  fullscreen = false,
  saving = false,
  onSave,
  onCancel,
}: {
  card: DraftCard
  /** Названия тем черновика — подсказки поля темы. */
  topics: string[]
  fullscreen?: boolean
  saving?: boolean
  onSave: (patch: CardPatch) => void
  onCancel: () => void
}) {
  const t = useT()
  const listId = useId()
  const [q, setQ] = useState(card.q)
  const [a, setA] = useState(card.a)
  const [note, setNote] = useState(card.note ?? '')
  const [topicText, setTopicText] = useState(card.topic ?? '')

  const ok = !!q.trim() && !!a.trim()

  function save() {
    if (!ok) return
    onSave({
      q: q.trim(),
      a: a.trim(),
      note: note.trim() || null,
      topic: topicText.trim() || null,
    })
  }

  const fields = (
    <>
      <Field label={t('cards.draft.edit.question')} htmlFor={`${listId}-q`} hint={t('cards.draft.edit.questionHint')}>
        <Textarea
          id={`${listId}-q`}
          rows={fullscreen ? 4 : 2}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="font-mono text-sm"
          autoFocus
        />
      </Field>
      <Field
        label={t('cards.draft.edit.answer')}
        htmlFor={`${listId}-a`}
        error={a.trim() ? undefined : t('cards.draft.edit.answerEmpty')}
      >
        <Textarea
          id={`${listId}-a`}
          rows={fullscreen ? 8 : 4}
          value={a}
          onChange={(e) => setA(e.target.value)}
          className="font-mono text-sm"
        />
      </Field>
      <Field label={t('cards.draft.edit.note')} htmlFor={`${listId}-n`} hint={t('cards.draft.edit.noteHint')}>
        <Textarea
          id={`${listId}-n`}
          rows={fullscreen ? 4 : 2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="font-mono text-sm"
        />
      </Field>
      <Field label={t('cards.draft.edit.topic')} htmlFor={`${listId}-t`} hint={t('cards.draft.edit.topicHint')}>
        <Input
          id={`${listId}-t`}
          list={`${listId}-topics`}
          value={topicText}
          onChange={(e) => setTopicText(e.target.value)}
          placeholder={t('cards.draft.noTopic')}
        />
        <datalist id={`${listId}-topics`}>
          {topics.map((title) => (
            <option key={title} value={title} />
          ))}
        </datalist>
      </Field>
    </>
  )

  if (fullscreen) {
    return (
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('cards.draft.edit.title')}
        className="fixed inset-0 z-[100] flex flex-col bg-surface"
      >
        <header className="flex items-center gap-s2 border-b border-line px-s3 pt-[calc(env(safe-area-inset-top)+8px)] pb-s2">
          <Button size="lg" variant="ghost" onClick={onCancel}>
            {t('common.action.cancel')}
          </Button>
          <span className="flex-1 truncate text-center font-semibold text-ink-strong">
            {t('cards.draft.edit.title')}
          </span>
          <Button size="lg" variant="primary" disabled={!ok} loading={saving} onClick={save}>
            {t('common.action.save')}
          </Button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-s3 overflow-y-auto px-s3 py-s3 pb-[calc(env(safe-area-inset-bottom)+16px)]">
          {fields}
        </div>
      </div>
    )
  }

  return (
    <div
      className={cn('flex flex-col gap-s3 rounded-md border border-accent bg-surface p-s3')}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel()
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) save()
      }}
    >
      {fields}
      <div className="flex flex-wrap items-center justify-end gap-s2">
        <span className="mr-auto text-xs text-muted">{t('cards.draft.edit.keys')}</span>
        <Button variant="ghost" onClick={onCancel}>
          {t('common.action.cancel')}
        </Button>
        <Button variant="primary" disabled={!ok} loading={saving} onClick={save}>
          {t('common.action.save')}
        </Button>
      </div>
    </div>
  )
}
