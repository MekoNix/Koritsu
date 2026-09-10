/**
 * BlockPicker — оглавление работы над вёрсткой и форма замечания к блоку.
 *
 * Блоки идут в порядке документа строками: ключ, заголовок, вид, кто написал и
 * пометка «черновик». Строка — не карточка: содержимое блока показывает сама
 * вёрстка под панелью, и второй его показ строкой означал бы, что человек
 * читает работу дважды в двух разных видах.
 *
 * **Панель стоит над превью, а выбор ведёт вёрстку к блоку.** Собранный
 * документ открыт встроенным просмотрщиком браузера, и попасть в нужный раздел
 * сорокастраничного отчёта можно только его же средствами — по имени закладки
 * (`pdfBlocks.bookmarkName`). Оглавление и есть тот список, из которого этот
 * переход делают.
 *
 * **Метка источника обязательна.** `agent` и `manual` — это ответ на вопрос
 * «кто это написал», и от него зависит, перепишет ли следующий проход текста
 * этот блок (написанное человеком не переписывается). Спрятать метку значило
 * бы спрятать причину, по которой блок остался прежним.
 *
 * **Черновик отличается от написанного.** Место под содержимое хранится не
 * пустым, а строкой с пометкой «черновик:» (`hokoku.live.DRAFT_MARK`): пустое
 * значение движок отчётов считает ошибкой сборки. Из-за этого черновик выглядит
 * в документе как обычный абзац, и незамеченным он уезжает в готовую работу.
 * Поэтому у него своя метка: «здесь ещё ничего нет» — это то, ради чего на
 * оглавление и смотрят.
 *
 * Форма замечания живёт рядом с оглавлением, а не в отдельном файле: адрес у
 * неё — тот же выбранный блок, и две половины одного разговора («какой блок» и
 * «что с ним не так») расходятся по файлам только вместе с этим адресом.
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

export function BlockPicker({
  blocks,
  loading,
  selected,
  onSelect,
}: {
  blocks: BlockRecordBody[] | undefined
  loading: boolean
  /** Выбранный блок — общий с вёрсткой и с формой замечания под ней. */
  selected: string | null
  onSelect: (ключ: string | null) => void
}) {
  const t = useT()
  const строки = useRef(new Map<string, HTMLLIElement>())

  // Панель невысока намеренно (работа из сорока блоков не должна отодвигать
  // вёрстку за край экрана), и выбранная строка в ней легко оказывается за
  // краем прокрутки. `nearest` — чтобы выбор видимой строки не дёргал список.
  useEffect(() => {
    if (selected) строки.current.get(selected)?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  if (loading) return <SkeletonLines count={4} />
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
    <ol
      className="max-h-[220px] overflow-auto rounded-md border border-line bg-surface"
      data-testid="kadai-block-picker"
    >
      {blocks.map((блок) => {
        const вид = String(блок.kind ?? '')
        const не_написан = черновик(вид, blockText(блок))
        const выбран = selected === блок.key
        return (
          <li
            key={блок.key}
            ref={(это) => {
              if (это) строки.current.set(блок.key, это)
              else строки.current.delete(блок.key)
            }}
          >
            <button
              type="button"
              aria-pressed={выбран}
              onClick={() => onSelect(выбран ? null : блок.key)}
              className={cn(
                'flex w-full items-center gap-s2 border-b border-line px-s2 py-1.5 text-left text-xs',
                'focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-accent',
                выбран ? 'bg-accent-bg text-ink-strong' : 'hover:bg-surface-2',
              )}
            >
              <span className="w-[4.5rem] shrink-0 truncate font-mono text-[11px] text-muted">
                {блок.key}
              </span>
              <Icon name={ЗНАЧОК[вид] ?? 'file'} size={13} className="shrink-0 text-muted" />
              <span
                className={cn(
                  'min-w-0 flex-1 truncate',
                  вид === 'heading' ? 'font-semibold text-ink-strong' : 'text-ink',
                  не_написан && 'text-muted',
                )}
              >
                {блок.label || блок.key}
              </span>
              <span className="shrink-0 text-[11px] text-muted">
                {ВИД[вид] ? t(ВИД[вид]) : вид || t('kadai.blocks.kind.unknown')}
              </span>
              {не_написан && (
                <span className="shrink-0 rounded-sm border border-warn bg-warn-bg px-1 py-0.5 text-[11px] text-warn">
                  {t('kadai.blocks.draft')}
                </span>
              )}
              <span
                className={cn(
                  'shrink-0 text-[11px]',
                  блок.source === 'manual' ? 'text-ink-strong' : 'text-agent',
                )}
              >
                {t(
                  блок.source === 'manual'
                    ? 'kadai.blocks.source.human'
                    : 'kadai.blocks.source.agent',
                )}
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

/**
 * Форма замечания к блоку: поле «что переделать» и три действия.
 *
 * Стоит под вёрсткой и всегда одна: блок выбирают оглавлением над страницей, а
 * говорят о нём здесь. Две одинаковые формы на одном экране — это вопрос «в
 * какую писать», а не выбор.
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
  const не_написан = черновик(вид, blockText(block))

  useEffect(() => setNote(''), [block.key])

  return (
    <div className="flex flex-col gap-s2 rounded-md border border-line bg-surface p-s3">
      <p className="flex flex-wrap items-center gap-s2 text-sm">
        <span className="font-semibold text-ink-strong">{t('kadai.blocks.note')}</span>
        <span className="truncate text-muted">{block.label || block.key}</span>
      </p>
      {не_написан && <p className="text-xs text-warn">{t('kadai.blocks.draftHint')}</p>}
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
