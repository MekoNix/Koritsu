/**
 * Settings — настройки захода: сколько вопросов, порядок, темы, какие вопросы, повтор «Нет».
 *
 * **Настройки личные.** У набора есть рекомендуемые (`defaults`), у человека — свои,
 * стартующие с рекомендуемых. «Сбросить к рекомендуемым» возвращает свои к ним; редактор
 * набора видит ещё «Сделать рекомендуемыми для всех» — текущие становятся стартом для
 * каждого, кто своих ещё не менял.
 *
 * **Две раскладки.** На компьютере — панель рядом со списком тем, всё видно сразу. На
 * телефоне — строка со сводкой («20 вопросов · По темам, внутри случайно»), по нажатию
 * открывается нижний лист с крупными переключателями: высота каждой цели не меньше
 * 44 px, переключатель срабатывает от нажатия на всю строку, а не только на сам тумблер.
 *
 * Компонент не пишет в службу: он отдаёт новое значение через `onChange`, а когда и как
 * записать — решает страница (у страницы набора — с задержкой, чтобы щелчки по галочкам
 * тем не уходили запросом каждый).
 */
import { useEffect, useId, useState, type ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon, Switch } from '@/ui'

import { useIsPhone } from '../hooks/useIsPhone'
import {
  CARD_INCLUDES,
  CARD_ORDERS,
  SESSION_ALL,
  SESSION_SIZE_MAX,
  SESSION_SIZES,
  sameSettings,
  type CardSettings,
  type CardTopic,
  type TopicChoice,
} from '../types'
import { BottomSheet } from './Sheet'
import { settingsSummary } from './settingsSummary'

export type SettingsProps = {
  value: CardSettings
  /** Рекомендуемые настройки набора. */
  defaults: CardSettings
  topics: CardTopic[]
  /** Есть ли в наборе карточки без темы — тогда в списке тем есть галочка «Без темы». */
  hasNoTopic: boolean
  /** Редактор набора: видит «Сделать рекомендуемыми для всех». */
  canEdit: boolean
  onChange: (next: CardSettings) => void
  onReset: () => void
  onMakeDefault?: () => void
  makingDefault?: boolean
  /** Идёт запись — маленькая подпись у заголовка панели. */
  saving?: boolean
  /** Текст беды записи, если была. */
  error?: string | null
  className?: string
}

export function Settings(props: SettingsProps) {
  const t = useT()
  const isPhone = useIsPhone()
  const [открыт, setОткрыт] = useState(false)
  const заголовок = useId()
  const совпадают = sameSettings(props.value, props.defaults)

  const сброс = (
    <Button variant="ghost" disabled={совпадают} onClick={props.onReset} className="justify-start max-[640px]:min-h-[44px]">
      <Icon name="restore" size={16} />
      {t('cards.settings.reset')}
    </Button>
  )
  const общие =
    props.canEdit && props.onMakeDefault ? (
      <Button
        variant="ghost"
        disabled={совпадают}
        loading={props.makingDefault}
        onClick={props.onMakeDefault}
        className="justify-start max-[640px]:min-h-[44px]"
      >
        <Icon name="users" size={16} />
        {t('cards.settings.makeDefault')}
      </Button>
    ) : null

  const форма = (
    <SettingsForm value={props.value} topics={props.topics} hasNoTopic={props.hasNoTopic} onChange={props.onChange} />
  )

  if (isPhone) {
    return (
      <>
        <button
          type="button"
          aria-haspopup="dialog"
          aria-expanded={открыт}
          onClick={() => setОткрыт(true)}
          className={cn(
            'flex min-h-[56px] w-full items-center gap-s3 rounded-md border border-line bg-surface px-s4 py-s2 text-left shadow-1',
            'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
            props.className,
          )}
        >
          <Icon name="settings" size={20} className="text-muted" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="text-sm font-semibold text-ink-strong">{t('cards.settings.title')}</span>
            <span className="truncate text-xs text-muted">{settingsSummary(t, props.value)}</span>
          </span>
          <Icon name="chevronRight" size={18} className="text-muted" />
        </button>
        <BottomSheet
          open={открыт}
          onOpenChange={setОткрыт}
          title={t('cards.settings.title')}
          description={t('cards.settings.personal')}
          footer={
            <>
              {сброс}
              {общие}
              <Button variant="primary" size="lg" onClick={() => setОткрыт(false)}>
                {t('cards.settings.done')}
              </Button>
            </>
          }
        >
          {форма}
          {props.error && <p className="mt-s3 text-sm text-err">{props.error}</p>}
        </BottomSheet>
      </>
    )
  }

  return (
    <section
      aria-labelledby={заголовок}
      className={cn('flex min-w-0 flex-col gap-s4 rounded-md border border-line bg-surface p-s4 shadow-1', props.className)}
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-s2">
          <h2 id={заголовок} className="m-0 font-display text-md font-semibold text-ink-strong">
            {t('cards.settings.title')}
          </h2>
          {props.saving && <span className="text-xs text-muted">{t('cards.settings.saving')}</span>}
        </div>
        <p className="m-0 text-xs text-muted">{t('cards.settings.personal')}</p>
      </div>
      {форма}
      {props.error && <p className="m-0 text-sm text-err">{props.error}</p>}
      <div className="flex flex-col gap-1 border-t border-line pt-s3">
        {сброс}
        {общие}
        {совпадают && <p className="m-0 px-s4 text-xs text-muted">{t('cards.settings.isDefault')}</p>}
      </div>
    </section>
  )
}

// ── форма ────────────────────────────────────────────────────────────────────

function Group({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  const id = useId()
  return (
    <div role="group" aria-labelledby={id} className="flex min-w-0 flex-col gap-s2">
      <div id={id} className="text-sm font-semibold text-ink-strong">
        {title}
      </div>
      {children}
      {hint && <p className="m-0 text-xs text-muted">{hint}</p>}
    </div>
  )
}

function Фишки<V extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: V
  options: { value: V; label: ReactNode }[]
  onChange: (v: V) => void
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-s2">
      {options.map((o) => {
        const выбран = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={выбран}
            onClick={() => onChange(o.value)}
            className={cn(
              'inline-flex min-h-[44px] min-w-[52px] items-center justify-center rounded-btn border px-s3 text-sm font-medium min-[641px]:min-h-[32px] min-[641px]:min-w-[44px]',
              'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
              выбран ? 'border-accent bg-accent-bg text-ink-strong' : 'border-line-strong bg-surface text-ink hover:bg-surface-2',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

function Кружок({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-2',
        on ? 'border-accent' : 'border-line-strong',
      )}
    >
      {on && <span className="h-2 w-2 rounded-full bg-accent" />}
    </span>
  )
}

function SettingsForm({
  value,
  topics,
  hasNoTopic,
  onChange,
}: {
  value: CardSettings
  topics: CardTopic[]
  hasNoTopic: boolean
  onChange: (next: CardSettings) => void
}) {
  const t = useT()
  const size = value.session_size
  const готовый = size === SESSION_ALL || SESSION_SIZES.includes(size)
  const [своё, setСвоё] = useState(!готовый)
  const [число, setЧисло] = useState(String(готовый ? 30 : size))

  // Сброс к рекомендуемым меняет размер снаружи — поле своего числа следует за ним.
  useEffect(() => {
    if (size === SESSION_ALL || SESSION_SIZES.includes(size)) setСвоё(false)
    else {
      setСвоё(true)
      setЧисло(String(size))
    }
  }, [size])

  const задать = (patch: Partial<CardSettings>) => onChange({ ...value, ...patch })

  const размер = своё ? 'custom' : size === SESSION_ALL ? 'all' : String(size)
  const размеры = [
    ...SESSION_SIZES.map((n) => ({ value: String(n), label: String(n) })),
    { value: 'all', label: t('cards.settings.sizeAll') },
    { value: 'custom', label: t('cards.settings.sizeCustom') },
  ]

  const выбратьРазмер = (v: string) => {
    if (v === 'custom') {
      setСвоё(true)
      const n = Math.min(Math.max(parseInt(число, 10) || 30, 1), SESSION_SIZE_MAX)
      задать({ session_size: n })
      return
    }
    setСвоё(false)
    задать({ session_size: v === 'all' ? SESSION_ALL : Number(v) })
  }

  const всеТемы: TopicChoice[] = [...topics.map((x) => x.id), ...(hasNoTopic ? [null] : [])]
  const отмечена = (id: TopicChoice) => value.topics === null || value.topics.includes(id)
  const переключитьТему = (id: TopicChoice) => {
    const было = value.topics ?? всеТемы
    const стало = было.includes(id) ? было.filter((x) => x !== id) : [...было, id]
    задать({ topics: всеТемы.every((x) => стало.includes(x)) ? null : стало })
  }
  const строкиТем: { id: TopicChoice; title: string }[] = [
    ...topics.map((x) => ({ id: x.id as TopicChoice, title: x.title })),
    ...(hasNoTopic ? [{ id: null, title: t('cards.common.noTopic') }] : []),
  ]

  return (
    <div className="flex flex-col gap-s5">
      <Group title={t('cards.settings.size')}>
        <Фишки label={t('cards.settings.size')} value={размер} options={размеры} onChange={выбратьРазмер} />
        {своё && (
          <label className="flex items-center gap-s3 text-sm text-ink">
            <span>{t('cards.settings.sizeCustomLabel')}</span>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={SESSION_SIZE_MAX}
              value={число}
              onChange={(e) => {
                setЧисло(e.target.value)
                const n = parseInt(e.target.value, 10)
                if (n >= 1) задать({ session_size: Math.min(n, SESSION_SIZE_MAX) })
              }}
              className="min-h-[44px] w-[110px] rounded-sm border border-line-strong bg-surface px-3 text-md text-ink focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-accent-bg min-[641px]:min-h-[36px] min-[641px]:text-sm"
            />
          </label>
        )}
      </Group>

      <Group title={t('cards.settings.order')}>
        <div role="radiogroup" aria-label={t('cards.settings.order')} className="flex flex-col gap-1">
          {CARD_ORDERS.map((o) => {
            const выбран = value.order === o
            return (
              <button
                key={o}
                type="button"
                role="radio"
                aria-checked={выбран}
                onClick={() => задать({ order: o })}
                className={cn(
                  'flex min-h-[44px] w-full items-start gap-s3 rounded-sm border px-s3 py-s2 text-left',
                  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                  выбран ? 'border-accent bg-accent-bg' : 'border-transparent hover:bg-surface-2',
                )}
              >
                <Кружок on={выбран} />
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm font-medium text-ink-strong">{t(`cards.settings.orders.${o}.title`)}</span>
                  <span className="text-xs text-muted">{t(`cards.settings.orders.${o}.text`)}</span>
                </span>
              </button>
            )
          })}
        </div>
      </Group>

      {строкиТем.length > 0 && (
        <Group
          title={t('cards.settings.topics')}
          hint={value.topics !== null && value.topics.length === 0 ? t('cards.settings.topicsNone') : undefined}
        >
          <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-s3 rounded-sm px-s1 text-sm font-medium text-ink">
            <span>{t('cards.settings.topicsAll')}</span>
            <Switch checked={value.topics === null} onChange={(e) => задать({ topics: e.target.checked ? null : [] })} />
          </label>
          <ul className="m-0 flex max-h-[300px] list-none flex-col overflow-y-auto rounded-sm border border-line p-0 max-[640px]:max-h-none">
            {строкиТем.map((row) => (
              <li key={row.id ?? '~none'} className="border-b border-line last:border-b-0">
                <label className="flex min-h-[44px] cursor-pointer items-center gap-s3 px-s3 py-s2 text-sm text-ink hover:bg-surface-2">
                  <input
                    type="checkbox"
                    checked={отмечена(row.id)}
                    onChange={() => переключитьТему(row.id)}
                    className="h-5 w-5 shrink-0 accent-[var(--accent)]"
                  />
                  <span className={cn('min-w-0 break-words', row.id === null && 'italic text-muted')}>{row.title}</span>
                </label>
              </li>
            ))}
          </ul>
        </Group>
      )}

      <Group title={t('cards.settings.include')} hint={t(`cards.settings.includes.${value.include}.text`)}>
        <Фишки
          label={t('cards.settings.include')}
          value={value.include}
          options={CARD_INCLUDES.map((v) => ({ value: v, label: t(`cards.settings.includes.${v}.title`) }))}
          onChange={(v) => задать({ include: v })}
        />
      </Group>

      <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-s3">
        <span className="flex min-w-0 flex-col">
          <span className="text-sm font-semibold text-ink-strong">{t('cards.settings.repeatWrong')}</span>
          <span className="text-xs text-muted">{t('cards.settings.repeatWrongHint')}</span>
        </span>
        <Switch
          checked={value.repeat_wrong}
          onChange={(e) => задать({ repeat_wrong: e.target.checked })}
          className="max-[640px]:scale-110"
        />
      </label>
    </div>
  )
}
