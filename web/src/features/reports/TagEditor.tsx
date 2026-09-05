/**
 * TagEditor — середина экрана: заполнение выбранного тега.
 *
 * Три действия над полем (правило интерфейса): сгенерировать, скопировать,
 * очистить. На время генерации поле заблокировано — не «только для чтения», а
 * именно `disabled`: правка, набранная поверх приходящего текста, была бы
 * потеряна первым же куском потока.
 *
 * **Полей два, по типу тега.** Текстовые типы
 * (`text`, `markdown`, `code`) правятся как текст; у остальных — таблицы,
 * картинки, схемы, формулы — полей больше одного, и «текстом» их не выразить.
 * Их значение правится JSON'ом в CodeMirror (`JsonEditor`), а форма проверяется
 * тем же правилом, что у службы (`values.validateValue`), до отправки. Раньше
 * такой тег просто не давали трогать — поле было заблокировано с подписью
 * «этот тип правится не текстом».
 *
 * **Отказ службы подписывается на поле.** У `invalid_value` есть `where`
 * (`body.rows`), и показывать его надо не строкой «что-то не так», а именем
 * поля: JSON на двадцать строк без указания места читается заново целиком.
 *
 * **Черновик локальный, отправляется по уходу из поля.** Каждое нажатие клавиши
 * в службу не уезжает: там у значения версия и история, и сорок версий на один
 * абзац сделали бы её нечитаемой. Поэтому правка копится в поле, а `PUT` уходит
 * на `blur` и по кнопке.
 *
 * **Очистить — это новая версия с пустым текстом**, а не удаление: удаления
 * значения у службы нет вовсе, и «очистить» обязано так же откатываться, как
 * всё прочее.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { errorField, errorText } from '@/api'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon, Spinner, Textarea } from '@/ui'

import { JsonEditor } from './JsonEditor'
import { TagVersions } from './TagVersions'
import { useSetTagPrompt, useSetValue } from './data'
import { isTextual, tagTitle, textToValue, valueText } from './tags'
import { blankValue, parseValue, valueToJson } from './values'
import type { ProjectTag, TagValue } from './types'

export type TagEditorProps = {
  projectId: string
  tag: ProjectTag | undefined
  value: TagValue | undefined
  /** Текст, приходящий по потоку прямо сейчас; `undefined` — прогон не идёт. */
  streamed: string | undefined
  /** Идёт ли прогон по этому тегу. */
  busy: boolean
  canEdit: boolean
  onGenerate: (key: string) => void
  /** Цена прогона и остаток месяца — показываются ДО нажатия. */
  /** Можно ли вообще звать модель (есть ли пресет с ключом). */
  canGenerate: boolean
}

export function TagEditor({
  projectId,
  tag,
  value,
  streamed,
  busy,
  canEdit,
  onGenerate,
  canGenerate,
}: TagEditorProps) {
  const t = useT()
  const save = useSetValue(projectId)

  // Тип решает, каким полем правится тег, и берётся у значения, а не у тега:
  // объявленный тип бывает угадан по метке, а лежит в теге то, что лежит.
  const тип = value?.type ?? tag?.type ?? 'markdown'
  const текстовый = isTextual(тип)
  // Что показывает поле, если человек ничего не набирал. У текстового тега это
  // текст значения, у прочих — его JSON, а на пустом теге — заготовка по типу:
  // пустые фигурные скобки не подсказывают ни имён полей, ни их вида.
  const серверный = текстовый ? valueText(value) : valueToJson(value, тип)
  const [draft, setDraft] = useState(серверный)
  const [dirty, setDirty] = useState(false)
  const [copied, setCopied] = useState(false)
  // Ключ, под который набран черновик: смена тега обязана сбрасывать поле,
  // иначе текст одного тега уедет в другой по первому же `blur`.
  const ключ = tag?.key ?? ''
  const прежний = useRef(ключ)

  // Разбор и проверка черновика — на каждое нажатие: беда обязана быть видна
  // под курсором, а не после «сохранить». Правило то же, что у службы.
  const разбор = useMemo(() => (текстовый ? null : parseValue(тип, draft)), [текстовый, тип, draft])

  useEffect(() => {
    if (прежний.current !== ключ) {
      прежний.current = ключ
      setDraft(серверный)
      setDirty(false)
      return
    }
    // Значение переписали не мы (прогон, откат, сосед по пространству) —
    // показываем пришедшее. Свою несохранённую правку при этом не трогаем:
    // потерять набранное хуже, чем показать устаревшее.
    if (!dirty) setDraft(серверный)
  }, [ключ, серверный, dirty])

  // Напечатанное потоком остаётся в поле и после конца прогона — до того, как
  // приедет перечитанное значение. Иначе текст на секунду пропадает: задание
  // уже кончилось, а ответ службы ещё в пути, и человек видит, как написанное
  // моделью исчезает. Печатать поток в поле имеет смысл только у текстового тега: у прочих поле
  // держит JSON, и куски прозы посреди него — это сломанный черновик.
  useEffect(() => {
    if (busy && streamed !== undefined && текстовый) setDraft(streamed)
  }, [busy, streamed, текстовый])

  const записать = useCallback(
    (текст: string) => {
      if (!tag) return
      if (isTextual(value?.type ?? tag.type)) {
        save.mutate({
          key: tag.key,
          value: textToValue(текст, { type: tag.type, previous: value }),
        })
        setDirty(false)
        return
      }
      // Нетекстовое пишется целиком тем, что набрано: `previous` здесь не
      // подмешивается намеренно — человек видит перед собой ВСЁ значение, и
      // поле, которое он стёр, он стёр.
      const разобрано = parseValue(value?.type ?? tag.type, текст)
      if (разобрано.problem) return
      save.mutate({ key: tag.key, value: разобрано.value as TagValue })
      setDirty(false)
    },
    [save, tag, value],
  )

  if (!tag) {
    return (
      <div className="flex h-full items-center justify-center p-s6 text-center text-sm text-muted">
        {t('reports.editor.pick')}
      </div>
    )
  }

  const показ = busy && streamed !== undefined && текстовый ? streamed : draft
  const заблокировано = busy || !canEdit
  const беда = разбор?.problem ?? null
  // Отказ службы подписывается тем же местом, что и своя проверка: у
  // `invalid_value` есть `where` (`body.rows`), и без него человек читает JSON
  // заново целиком.
  const место_службы = save.isError ? errorField(save.error) : undefined

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-s2 border-b border-line p-s3">
        <span
          className={cn(
            'rounded-sm border px-1.5 py-0.5 font-mono text-xs',
            tag.source === 'agent'
              ? 'border-transparent bg-agent-bg text-agent'
              : 'border-line-strong text-ink',
          )}
        >{`{{${tag.key}}}`}</span>
        <span className="truncate font-semibold text-ink-strong">{tagTitle(tag)}</span>
        <span className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-xs text-muted">{tag.type}</span>
        {tag.filled && (
          <span className="text-xs text-muted">
            {t(tag.source === 'agent' ? 'reports.editor.byAgent' : 'reports.editor.byHand', {
              n: tag.version ?? 0,
            })}
          </span>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-s3 overflow-auto p-s3">
        <div className="flex flex-wrap items-center gap-s2">
          <Button
            variant="agent"
            size="sm"
            disabled={!canEdit || busy || !canGenerate}
            onClick={() => onGenerate(tag.key)}
          >
            {busy ? <Spinner size={14} /> : <Icon name="agent" size={14} />}
            {t('reports.editor.generate')}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void navigator.clipboard?.writeText(показ)
              setCopied(true)
              window.setTimeout(() => setCopied(false), 1500)
            }}
          >
            {copied ? t('common.action.copied') : t('common.action.copy')}
          </Button>
          {текстовый ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={заблокировано || (!показ && !tag.filled)}
              onClick={() => {
                setDraft('')
                записать('')
              }}
            >
              {t('reports.editor.clear')}
            </Button>
          ) : (
            // У нетекстового значения «пустого» не бывает: пустая таблица —
            // это `rows: []`, и render считает её ошибкой. Поэтому здесь не
            // «очистить», а «вернуть заготовку» — и в службу она не уезжает,
            // пока человек её не заполнит и не сохранит.
            <Button
              variant="ghost"
              size="sm"
              disabled={заблокировано}
              onClick={() => {
                setDraft(JSON.stringify(blankValue(тип), null, 2))
                setDirty(true)
              }}
            >
              {t('reports.editor.template')}
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            disabled={!dirty || заблокировано || !!беда}
            loading={save.isPending}
            onClick={() => записать(draft)}
          >
            {t('common.action.save')}
          </Button>
        </div>

        <TagPrompt projectId={projectId} tag={tag} canEdit={canEdit && !busy} />

        {текстовый ? (
          <Textarea
            value={показ}
            disabled={заблокировано}
            aria-label={t('reports.editor.field', { tag: tag.key })}
            onChange={(e) => {
              setDraft(e.target.value)
              setDirty(true)
            }}
            onBlur={() => {
              if (dirty) записать(draft)
            }}
            className={cn(
              'min-h-[220px] flex-1 font-body text-md leading-relaxed',
              busy && 'text-agent',
            )}
          />
        ) : (
          <div
            className={cn(
              'min-h-[220px] flex-1 overflow-auto rounded-md border bg-surface',
              беда ? 'border-err' : 'border-line',
            )}
          >
            <JsonEditor
              value={показ}
              readOnly={заблокировано}
              ariaLabel={t('reports.editor.jsonField', { tag: tag.key })}
              onChange={(текст) => {
                setDraft(текст)
                setDirty(true)
              }}
              onBlur={() => {
                if (dirty && !беда) записать(draft)
              }}
            />
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-s2 text-xs text-muted">
          <span>
            {текстовый ? t('reports.editor.chars', { n: показ.length }) : t('reports.json.hint')}
          </span>
          {save.isError && (
            <span className="text-err">
              {errorText(save.error)}
              {место_службы ? ` · ${t('reports.json.at', { field: место_службы })}` : ''}
            </span>
          )}
        </div>

        {беда && (
          <p className="rounded-md border border-err bg-err-bg px-s3 py-s2 text-xs text-err">
            {t(`reports.json.error.${беда.code}`)}
            {беда.field ? ` · ${t('reports.json.at', { field: беда.field })}` : ''}
          </p>
        )}

        <TagVersions
          projectId={projectId}
          tagKey={tag.key}
          canEdit={canEdit && !busy}
          currentText={серверный}
        />
      </div>
    </div>
  )
}

/**
 * TagPrompt — что модели велено написать в этом теге.
 *
 * Поле стоит прямо над значением, а не прячется в настройках работы: человек
 * пишет задание ровно в ту минуту, когда смотрит на пустой тег и решает, чего
 * он от него хочет. Прежде задание задавалось только комментарием в бланке —
 * то есть в Word, до начала работы, — и поправить его с сайта было нельзя.
 *
 * Комментарий бланка (`{# … #}`) приезжает сюда же: служба кладёт его в это
 * поле при разборе шаблона. Поэтому поле бывает заполнено само, и правка
 * человека дальше сильнее бланка.
 *
 * Отправляется по уходу из поля, как и значение: задание живёт в манифесте, а
 * тот считает каждую запись правкой, и версия манифеста на каждое нажатие
 * клавиши сделала бы счётчик бессмысленным.
 */
function TagPrompt({
  projectId,
  tag,
  canEdit,
}: {
  projectId: string
  tag: ProjectTag
  canEdit: boolean
}) {
  const t = useT()
  const save = useSetTagPrompt(projectId)
  const [draft, setDraft] = useState(tag.prompt)
  const [dirty, setDirty] = useState(false)
  const прежний = useRef(tag.key)

  useEffect(() => {
    if (прежний.current !== tag.key) {
      прежний.current = tag.key
      setDraft(tag.prompt)
      setDirty(false)
      return
    }
    if (!dirty) setDraft(tag.prompt)
  }, [tag.key, tag.prompt, dirty])

  return (
    <Textarea
      label={t('reports.editor.promptLabel')}
      hint={t('reports.editor.promptHint')}
      value={draft}
      disabled={!canEdit}
      maxLength={4000}
      placeholder={t('reports.editor.promptPlaceholder')}
      className="min-h-[64px] text-sm"
      onChange={(e) => {
        setDraft(e.target.value)
        setDirty(true)
      }}
      onBlur={() => {
        if (!dirty) return
        setDirty(false)
        save.mutate({ key: tag.key, prompt: draft })
      }}
    />
  )
}
