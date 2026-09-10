/**
 * BlockList — оглавление работы: блоки в порядке документа.
 *
 * Список рисует сам сайт — заголовок, текст, код, таблица, схема, — с именем и
 * меткой источника. Быстро и без сборки. Настоящая вёрстка (поля, переносы,
 * номера рисунков) считается только Word/LibreOffice, поэтому рядом на экране
 * всегда есть «как будет в Word»; здесь её нет и притворяться ею нельзя.
 *
 * **Метка источника обязательна.** `agent` и `manual` — это ответ на вопрос
 * «кто это написал», и от него зависит, перепишет ли следующий проход текста
 * этот блок (написанное человеком не переписывается). Спрятать метку значило
 * бы спрятать причину, по которой блок остался прежним.
 *
 * **Выбранный блок — общий с вёрсткой.** Какой блок выбран, знает экран
 * решения, а не карточка: тот же блок обведён рамкой на странице собранного
 * документа, и два своих «выбрано» — в списке и в вёрстке — разъехались бы на
 * первом же клике.
 *
 * **Форма замечания — там, где блок выбирают.** Блок, попавший в вёрстку,
 * выбирают прямо на странице, и форма стоит под ней (`PdfBlocks`); в карточке
 * её тогда нет — две одинаковые формы на одном экране это вопрос «в какую
 * писать», а не выбор. Блок, которого в вёрстке нет (работа ещё не собиралась,
 * заготовку пропустили при сборке), выбрать негде, кроме списка, — и форма
 * остаётся в карточке.
 *
 * **Черновик отличается от написанного.** Место под содержимое хранится не
 * пустым, а строкой с пометкой «черновик:» (`hokoku.live.DRAFT_MARK`): пустое
 * значение движок отчётов считает ошибкой сборки. Из-за этого черновик выглядит
 * как обычный блок с текстом, и незамеченным он уезжает в готовый документ.
 * Поэтому у него своя метка и приглушённая карточка: «здесь ещё ничего нет» —
 * это то, ради чего на список и смотрят.
 */
import { useEffect, useRef, useState } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, EmptyState, Icon, SkeletonLines, Textarea, type IconName } from '@/ui'

import { blockText, черновик, ВИД, type ReworkKind } from './stages'
import type { BlockRecordBody } from './types'

/**
 * Значок по виду блока. Вид приходит от движка отчётов (`hokoku.live.KINDS`).
 *
 * Один значок на два разных вида — хуже, чем никакого: листинг и схема с общим
 * знаком читаются как одно и то же, а разница между ними в замечании решает,
 * что именно переигрывать (`вид_замечания`). Поэтому у листинга свой знак
 * (строки кода), у таблицы — сетка, у схемы — блок-схема.
 */
const ЗНАЧОК: Record<string, IconName> = {
  heading: 'file',
  markdown: 'file',
  text: 'file',
  code: 'queue',
  table: 'dashboard',
  diagram: 'flowchart',
  image: 'eye',
  formula: 'chart',
  toc: 'tasks',
}

export type ReworkRequest = { block: string; kind: ReworkKind; note: string }

export function BlockList({
  blocks,
  loading,
  disabled,
  selected,
  onSelect,
  pickable,
  onRework,
}: {
  blocks: BlockRecordBody[] | undefined
  loading: boolean
  /** Идёт прогон: поле замечания заблокировано. */
  disabled: boolean
  /** Выбранный блок — общий с вёрсткой. */
  selected: string | null
  onSelect: (ключ: string | null) => void
  /** Ключи блоков, которые можно выбрать прямо на странице вёрстки. */
  pickable: ReadonlySet<string>
  onRework: (запрос: ReworkRequest) => void
}) {
  const t = useT()
  const карточки = useRef(new Map<string, HTMLLIElement>())

  // Выбор на странице вёрстки виден и в списке: в длинном списке подсвеченная
  // карточка легко оказывается за краем экрана, и выбор читается как «ничего не
  // произошло». `nearest` — чтобы клик по видимой карточке не дёргал список.
  useEffect(() => {
    if (selected) карточки.current.get(selected)?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  if (loading) return <SkeletonLines count={8} />
  if (!blocks || blocks.length === 0) {
    return (
      <EmptyState
        icon="tasks"
        title={t('kadai.blocks.emptyTitle')}
        text={t('kadai.blocks.emptyText')}
      />
    )
  }

  return (
    <ol className="flex flex-col gap-s2">
      {blocks.map((блок, i) => (
        <li
          key={блок.key}
          ref={(это) => {
            if (это) карточки.current.set(блок.key, это)
            else карточки.current.delete(блок.key)
          }}
        >
          <BlockCard
            block={блок}
            n={i + 1}
            open={selected === блок.key}
            onToggle={() => onSelect(selected === блок.key ? null : блок.key)}
            onPage={pickable.has(блок.key)}
            disabled={disabled}
            onRework={onRework}
          />
        </li>
      ))}
    </ol>
  )
}

function BlockCard({
  block,
  n,
  open,
  onToggle,
  onPage,
  disabled,
  onRework,
}: {
  block: BlockRecordBody
  n: number
  open: boolean
  onToggle: () => void
  /** Блок есть в вёрстке: замечание пишут там, под страницей. */
  onPage: boolean
  disabled: boolean
  onRework: (запрос: ReworkRequest) => void
}) {
  const t = useT()
  const вид = String(block.kind ?? '')
  const текст = blockText(block)
  const заголовок = вид === 'heading'
  const не_написан = черновик(вид, текст)

  return (
    <article
      className={cn(
        'rounded-md border shadow-1 transition-colors',
        // Черновик приглушён и обведён пунктиром: карточка, неотличимая от
        // готовой, читается как готовая — и человек узнаёт про пустое место
        // из собранного документа, а не из списка.
        не_написан ? 'border-dashed bg-surface-2' : 'bg-surface',
        open ? 'border-accent' : 'border-line hover:border-line-strong',
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-s2 p-s3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span className="mt-0.5 font-mono text-[11px] text-muted">{n}</span>
        <Icon name={ЗНАЧОК[вид] ?? 'file'} size={15} className="mt-0.5 shrink-0 text-muted" />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-s2">
            <span
              className={cn(
                'truncate',
                заголовок
                  ? 'font-display text-base font-semibold text-ink-strong'
                  : 'font-medium text-ink-strong',
                не_написан && 'text-muted',
              )}
            >
              {block.label || block.key}
            </span>
            <span className="rounded-sm border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">
              {ВИД[вид] ? t(ВИД[вид]) : вид || t('kadai.blocks.kind.unknown')}
            </span>
            {не_написан && (
              <span className="rounded-sm border border-warn bg-warn-bg px-1.5 py-0.5 text-[11px] text-warn">
                {t('kadai.blocks.draft')}
              </span>
            )}
            <span
              className={cn(
                'rounded-sm px-1.5 py-0.5 text-[11px]',
                block.source === 'manual' ? 'bg-accent-bg text-ink-strong' : 'text-agent',
              )}
            >
              {t(
                block.source === 'manual'
                  ? 'kadai.blocks.source.human'
                  : 'kadai.blocks.source.agent',
              )}
            </span>
          </span>
          {текст && (
            <span
              className={cn(
                'line-clamp-3 whitespace-pre-wrap text-xs text-muted',
                не_написан && 'italic',
              )}
            >
              {текст}
            </span>
          )}
          {не_написан && !текст && (
            <span className="text-xs italic text-muted">{t('kadai.blocks.draftEmpty')}</span>
          )}
        </span>
        <Icon
          name={open ? 'chevronDown' : 'chevronRight'}
          size={15}
          className="mt-0.5 text-muted"
        />
      </button>

      {open && (
        <div className="flex flex-col gap-s2 border-t border-line p-s3">
          {текст && (
            <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-surface-2 p-s2 font-mono text-xs text-ink">
              {текст}
            </pre>
          )}
          {не_написан && <p className="text-xs text-warn">{t('kadai.blocks.draftHint')}</p>}
          {onPage ? (
            <p className="text-xs text-muted">{t('kadai.blocks.onPage')}</p>
          ) : (
            <ReworkForm block={block} disabled={disabled} onRework={onRework} />
          )}
        </div>
      )}
    </article>
  )
}

/**
 * Форма замечания к блоку: поле «что переделать» и три действия.
 *
 * Отдельным куском, потому что блок выбирают в двух местах — в списке и прямо
 * на странице собранного документа, — а форма у них одна и та же. Разъехавшись,
 * две формы отправили бы одно и то же замечание по-разному, и разницу человек
 * увидел бы только по итогу переигранной работы.
 *
 * **Три действия уезжают одним `kadai_rework`.** «Убрать» и «переставить» — это
 * правка строения, поэтому у них вид `структура`, а само действие сказано
 * словами в замечании: своего вида «убери блок» у службы нет, и выдумывать его
 * на стороне сайта значило бы гадать, что сделает сценарий.
 *
 * Поле сбрасывается при смене блока: недописанная фраза про один блок, оставшаяся
 * в форме другого, — это замечание не по адресу, отправленное не глядя.
 */
export function ReworkForm({
  block,
  disabled,
  onRework,
}: {
  block: BlockRecordBody
  disabled: boolean
  onRework: (запрос: ReworkRequest) => void
}) {
  const t = useT()
  const [note, setNote] = useState('')
  const вид = String(block.kind ?? '')

  useEffect(() => setNote(''), [block.key])

  return (
    <div className="flex flex-col gap-s2">
      <Textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        disabled={disabled}
        placeholder={t('kadai.blocks.notePlaceholder')}
        aria-label={t('kadai.blocks.note')}
      />
      <div className="flex flex-wrap items-center gap-s2">
        <Button
          variant="primary"
          size="sm"
          disabled={disabled || !note.trim()}
          onClick={() => onRework({ block: block.key, kind: вид_замечания(вид), note })}
        >
          {t('kadai.blocks.redo')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={disabled}
          onClick={() =>
            onRework({
              block: block.key,
              kind: 'структура',
              note: `${t('kadai.blocks.removeNote')}: ${block.label || block.key}${note.trim() ? `. ${note.trim()}` : ''}`,
            })
          }
        >
          {t('kadai.blocks.remove')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={disabled || !note.trim()}
          onClick={() =>
            onRework({
              block: block.key,
              kind: 'структура',
              note: `${t('kadai.blocks.moveNote')}: ${block.label || block.key}. ${note.trim()}`,
            })
          }
        >
          {t('kadai.blocks.move')}
        </Button>
        <span className="text-xs text-muted">{t('kadai.blocks.noteHint')}</span>
      </div>
    </div>
  )
}

/**
 * Вид замечания по виду блока: текст — «кусок», код — «код», схема — «схема».
 *
 * Угадывать вид по словам замечания нельзя (`kadai.rework`: «маршрут по словам
 * не угадывается»), а по виду блока он известен точно: замечание к листингу —
 * это замечание к коду, и переигрывать после него надо больше, чем один абзац.
 */
function вид_замечания(kind: string): ReworkKind {
  if (kind === 'code') return 'код'
  if (kind === 'diagram' || kind === 'image') return 'схема'
  return 'кусок'
}
