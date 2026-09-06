/**
 * RunName — имя запуска, которое правится на месте.
 *
 * Имя запуска показывается в трёх местах сразу: строкой в «Что в работе»,
 * строкой в списке модуля и заголовком на экране схемы. Править его человек
 * хочет там, где увидел, — а не на четвёртой странице, — поэтому правка
 * встроена в само имя: карандаш рядом или двойной щелчок по тексту, поле,
 * `Enter` — сохранить, `Esc` — вернуть как было.
 *
 * **Поле хранит то, что написал человек, а не то, что видно.** Видно бывает имя
 * по умолчанию («Схема 2 — Курсовая»), которое рисует сайт из модуля и номера;
 * подставить его в поле значило бы превратить его в собственное имя записи от
 * одного нажатия `Enter`. Поэтому в поле лежит `name` как есть (часто пустой), а
 * имя по умолчанию стоит подсказкой: стёр своё — снова видишь то, что было.
 *
 * Уход из поля сохраняет, как и `Enter`: поле без кнопок, и «щёлкнул мимо»
 * читается как «дописал», а не как «передумал». Передумать — `Esc`.
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon, useToast } from '@/ui'

import { useRenameProjectRun } from './data'

export type RunNameProps = {
  projectId: string
  runId: string
  /** Имя как его хранит служба: пусто — имя рисует сайт. */
  name: string
  /** Что видно, пока своего имени нет («Схема 2 — Курсовая»). */
  title: string
  /** Нет роли editor — имя только читается. */
  canEdit?: boolean
  /** Разметка показанного имени: строка списка и заголовок выглядят по-разному. */
  className?: string
  /** Размер карандаша под соседние кнопки строки. */
  iconSize?: number
  /**
   * Куда ведёт имя, если оно ссылка. Тогда двойного щелчка по нему нет: в
   * ссылке он открывает её, а не поле, — и правка началась бы на другой
   * странице. Карандаш работает всегда.
   */
  href?: string
  /**
   * Новое имя тому, кто держит запись у себя в состоянии (экран схемы).
   *
   * Списки узнают имя перезапросом — `useRenameProjectRun` гасит их ключи, — а
   * экран схемы наполняется из ответа один раз и перезапросом его не
   * переписывает: иначе открытая схема стирала бы правки в поле кода.
   */
  onRenamed?: (name: string) => void
}

export function RunName({
  projectId,
  runId,
  name,
  title,
  canEdit = true,
  className,
  iconSize = 14,
  href,
  onRenamed,
}: RunNameProps) {
  const t = useT()
  const toast = useToast()
  const rename = useRenameProjectRun()
  const [правится, setПравится] = useState(false)
  const [черновик, setЧерновик] = useState(name)
  const поле = useRef<HTMLInputElement | null>(null)
  // Уход из поля сохраняет, а `Esc` — нет, и различить их можно только флагом:
  // `Esc` снимает поле с экрана, а снятие поля — это и есть уход из него.
  const отменено = useRef(false)

  useEffect(() => {
    if (правится) поле.current?.select()
  }, [правится])

  function начать() {
    setЧерновик(name)
    отменено.current = false
    setПравится(true)
  }

  function сохранить() {
    setПравится(false)
    if (отменено.current) return
    const новое = черновик.trim()
    if (новое === name.trim()) return
    rename.mutate(
      { projectId, runId, name: новое },
      {
        onSuccess: (запись) => onRenamed?.(запись.name),
        onError: (беда) => toast.fail(беда, t('projects.runs.renameFailed')),
      },
    )
  }

  if (правится) {
    return (
      <input
        ref={поле}
        autoFocus
        value={черновик}
        aria-label={t('projects.runs.rename', { name: title })}
        placeholder={title}
        maxLength={200}
        className={cn(
          'min-w-0 flex-1 rounded-sm border border-accent bg-surface px-2 py-1 text-sm text-ink-strong',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent',
        )}
        onChange={(событие) => setЧерновик(событие.target.value)}
        onBlur={сохранить}
        onKeyDown={(событие) => {
          if (событие.key === 'Enter') {
            событие.preventDefault()
            поле.current?.blur()
          }
          if (событие.key === 'Escape') {
            событие.preventDefault()
            отменено.current = true
            setПравится(false)
          }
        }}
      />
    )
  }

  return (
    <span className="flex min-w-0 items-center gap-1">
      {href ? (
        <Link to={href} className={cn('truncate transition-colors hover:text-accent', className)}>
          {title}
        </Link>
      ) : (
        <span
          className={cn('truncate', className)}
          onDoubleClick={canEdit ? начать : undefined}
          title={title}
        >
          {title}
        </span>
      )}
      {canEdit && (
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          loading={rename.isPending}
          aria-label={t('projects.runs.rename', { name: title })}
          onClick={начать}
        >
          <Icon name="edit" size={iconSize} />
        </Button>
      )}
    </span>
  )
}
