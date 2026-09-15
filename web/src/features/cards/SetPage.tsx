/**
 * SetPage — набор карточек: мой прогресс, темы, настройки захода, быстрые старты, список.
 *
 *     /cards/:projectId/:setId
 *
 * **Что здесь делают.** Смотрят, что знают (доля «знаю» по набору и по темам),
 * настраивают заход под себя и начинают: «Заход по настройкам», «Повторить мои «Нет»»,
 * «Весь набор подряд». Нажатие по теме фильтрует список карточек ниже. Редактор
 * набора (владелец или редактор пространства) ещё заменяет файл, дополняет набор
 * агентом, переименовывает и удаляет; скачать `.json` может каждый.
 *
 * **«Продолжить заход»** — мой незаконченный заход текущей версии моложе 12 часов,
 * по службе (`GET …/sessions/open`), поэтому начатый на телефоне заход продолжается
 * на компьютере и наоборот.
 *
 * **Настройки пишутся сами.** Правка уходит в службу через 600 мс после последнего
 * щелчка; быстрый старт дописывает незаписанную правку до того, как завести заход, —
 * иначе заход разложился бы по прежним настройкам. Уход со страницы тоже дописывает её.
 *
 * **Две раскладки.** На компьютере — прогресс и темы слева, панель настроек справа
 * рядом с ними, список карточек во всю ширину ниже; действия с набором — кнопками в
 * шапке. На телефоне — одна колонка: сводка настроек строкой с нижним листом, действия
 * — в меню «…» у заголовка, а «Заход по настройкам» закреплён внизу экрана.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import {
  BetaTag,
  Button,
  ErrorState,
  Icon,
  MenuContent,
  MenuItem,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
  Progress,
  SkeletonLines,
  useToast,
} from '@/ui'
import { canEditWorkspace } from '@/features/projects/data'

import {
  putMySettings,
  useCardSet,
  useDownloadCardSet,
  useOpenSession,
  usePutDefaults,
  usePutMySettings,
  useStartSession,
} from './api'
import { CardsList } from './components/CardsList'
import { ReplaceDialog } from './components/ReplaceDialog'
import { DeleteDialog, RenameDialog } from './components/SetDialogs'
import { Settings } from './components/Settings'
import { settingsSummary } from './components/settingsSummary'
import { useIsPhone } from './hooks/useIsPhone'
import { cardsPaths, type PlayLocationState } from './paths'
import {
  NO_TOPIC,
  knownPercent,
  settingsOf,
  type CardSet,
  type CardSettings,
  type SessionPreset,
} from './types'

type Диалог = 'replace' | 'rename' | 'delete' | null

export function SetPage() {
  const t = useT()
  const navigate = useNavigate()
  const toast = useToast()
  const isPhone = useIsPhone()
  const { projectId = '', setId = '' } = useParams()
  const workspace = useCurrentWorkspace()
  const set = useCardSet(projectId, setId)
  const download = useDownloadCardSet()
  const start = useStartSession()
  const openSession = useOpenSession(projectId, setId)
  const settings = useSetSettings(projectId, setId, set.data)
  useDocumentCrumb(set.data?.title)

  const [тема, setТема] = useState('')
  const [диалог, setДиалог] = useState<Диалог>(null)
  const [стартует, setСтартует] = useState<SessionPreset | null>(null)
  const [пустойЗаход, setПустойЗаход] = useState(false)
  const список = useRef<HTMLElement>(null)

  if (set.isPending) return <SkeletonLines count={6} />
  if (set.isError) {
    return (
      <ErrorState
        error={set.error}
        onRetry={() => void set.refetch()}
        action={
          <Button asChild variant="ghost">
            <Link to={cardsPaths.library}>{t('cards.common.back')}</Link>
          </Button>
        }
      />
    )
  }

  const data = set.data
  const canEdit = data.can_edit ?? canEditWorkspace(workspace.data?.role)
  const поТемам = new Map((data.my_progress?.by_topic ?? []).map((x) => [x.topic ?? NO_TOPIC, x]))
  const естьБезТемы = поТемам.has(NO_TOPIC)
  const открытый = openSession.data ?? null
  const известно = data.my_progress?.known ?? 0
  const всего = data.my_progress?.total ?? data.cards_count
  const процент = knownPercent(известно, всего)

  const начать = async (preset: SessionPreset) => {
    setСтартует(preset)
    setПустойЗаход(false)
    try {
      await settings.flush()
      const session = await start.mutateAsync({ projectId, setId, preset })
      if (!session.keys.length) {
        setПустойЗаход(true)
        return
      }
      const state: PlayLocationState = { start: session }
      navigate(cardsPaths.play(projectId, setId, session.session_id), { state })
    } catch (беда) {
      toast.fail(беда, t('cards.common.startFailed'))
    } finally {
      setСтартует(null)
    }
  }

  const скачать = () =>
    download.mutate(
      { projectId, setId, title: data.title },
      { onError: (беда) => toast.fail(беда, t('cards.set.downloadFailed')) },
    )
  const дополнить = () => navigate(cardsPaths.generate({ projectId, setId }))

  const выбратьТему = (id: string) => {
    setТема(id)
    requestAnimationFrame(() => список.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  const счёт = (id: string) => {
    const x = поТемам.get(id)
    return { known: x?.known ?? 0, total: x?.total ?? 0 }
  }
  const строкиТем = [
    ...data.topics.map((x) => ({ id: x.id, title: x.title, ...счёт(x.id) })),
    ...(естьБезТемы ? [{ id: NO_TOPIC, title: t('cards.common.noTopic'), ...счёт(NO_TOPIC) }] : []),
  ]
  const продолжить = () => {
    if (открытый?.session_id) navigate(cardsPaths.play(projectId, setId, открытый.session_id))
  }
  const оценено = открытый ? new Set(открытый.answers.map((a) => a.key)).size : 0

  const панельНастроек = (
    <Settings
      value={settings.value}
      defaults={settings.defaults}
      topics={data.topics}
      hasNoTopic={естьБезТемы}
      canEdit={canEdit}
      onChange={settings.change}
      onReset={() => settings.change(settings.defaults)}
      onMakeDefault={settings.makeDefault}
      makingDefault={settings.makingDefault}
      saving={settings.saving}
      error={settings.error}
      className={isPhone ? undefined : 'min-[961px]:sticky min-[961px]:top-[calc(var(--topbar-h)+var(--space-3))]'}
    />
  )

  const меню = (
    <MenuRoot>
      <MenuTrigger asChild>
        <Button variant={isPhone ? 'ghost' : 'secondary'} size={isPhone ? 'lg' : 'md'} iconOnly aria-label={t('cards.set.actions')}>
          <Icon name="more" size={20} />
        </Button>
      </MenuTrigger>
      <MenuContent className="max-w-[calc(100vw-24px)]">
        {isPhone && (
          <MenuItem className="min-h-[44px]" icon={<Icon name="download" size={18} />} onSelect={скачать}>
            {t('cards.set.download')}
          </MenuItem>
        )}
        {isPhone && canEdit && (
          <>
            <MenuItem className="min-h-[44px]" icon={<Icon name="refresh" size={18} />} onSelect={() => setДиалог('replace')}>
              {t('cards.set.replace')}
            </MenuItem>
            <MenuItem className="min-h-[44px]" icon={<Icon name="agent" size={18} />} onSelect={дополнить}>
              {t('cards.set.supplement')}
            </MenuItem>
            <MenuSeparator />
          </>
        )}
        {canEdit && (
          <>
            <MenuItem className="min-h-[44px] min-[641px]:min-h-0" icon={<Icon name="edit" size={18} />} onSelect={() => setДиалог('rename')}>
              {t('cards.set.rename')}
            </MenuItem>
            <MenuItem
              danger
              className="min-h-[44px] min-[641px]:min-h-0"
              icon={<Icon name="trash" size={18} />}
              onSelect={() => setДиалог('delete')}
            >
              {t('cards.set.delete')}
            </MenuItem>
          </>
        )}
      </MenuContent>
    </MenuRoot>
  )

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex min-w-0 flex-col gap-s2">
        <Link to={cardsPaths.library} className="inline-flex min-h-[44px] items-center gap-1 self-start text-sm text-muted min-[641px]:min-h-0">
          <Icon name="arrowLeft" size={16} />
          {t('cards.common.back')}
        </Link>
        <div className="flex items-start justify-between gap-s3">
          <div className="min-w-0 flex-1">
            <h1 className="m-0 flex flex-wrap items-center gap-s2 break-words font-display text-2xl font-semibold text-ink-strong max-[640px]:text-xl">
              <span className="min-w-0 break-words">{data.title || t('cards.common.untitled')}</span>
              <BetaTag label={t('shell.beta')} />
            </h1>
            {data.description && <p className="m-0 mt-1 max-w-[72ch] break-words text-sm text-muted">{data.description}</p>}
            <p className="m-0 mt-1 text-xs text-muted">
              {t('cards.common.topicsCount', { n: data.topics.length })} · {t('cards.common.cardsCount', { n: data.cards_count })} ·{' '}
              {t('cards.set.version', { n: data.version })}
            </p>
          </div>
          {isPhone ? (
            меню
          ) : (
            <div className="flex shrink-0 flex-wrap items-center justify-end gap-s2">
              <Button variant="secondary" loading={download.isPending} onClick={скачать}>
                <Icon name="download" size={16} />
                {t('cards.set.download')}
              </Button>
              {canEdit && (
                <>
                  <Button variant="secondary" onClick={() => setДиалог('replace')}>
                    <Icon name="refresh" size={16} />
                    {t('cards.set.replace')}
                  </Button>
                  <Button variant="agent" onClick={дополнить}>
                    <Icon name="agent" size={16} />
                    {t('cards.set.supplement')}
                  </Button>
                  {меню}
                </>
              )}
            </div>
          )}
        </div>
      </header>

      <div className="grid items-start gap-s5 min-[961px]:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
        <div className="flex min-w-0 flex-col gap-s5">
          <section aria-labelledby="set-progress" className="flex flex-col gap-s3 rounded-md border border-line bg-surface p-s4 shadow-1">
            <div className="flex items-baseline justify-between gap-s3">
              <h2 id="set-progress" className="m-0 font-display text-md font-semibold text-ink-strong">
                {t('cards.set.progress')}
              </h2>
              <span className="font-mono text-sm text-ink-strong">{t('cards.common.knownPercent', { p: процент })}</span>
            </div>
            <Progress value={процент / 100} tone={процент === 100 ? 'ok' : 'accent'} label={t('cards.set.progress')} />
            <p className="m-0 text-xs text-muted">{t('cards.common.knownOf', { known: известно, total: всего })}</p>

            {isPhone && панельНастроек}

            {открытый && (
              <Старт
                primary
                title={t('cards.set.continue')}
                hint={t('cards.set.continueHint', { pos: оценено, total: new Set(открытый.keys).size })}
                disabled={!!стартует}
                onClick={продолжить}
              />
            )}

            <div className="grid gap-s2 min-[641px]:grid-cols-3">
              {!isPhone && (
                <Старт
                  primary
                  title={t('cards.set.startSettings')}
                  hint={settingsSummary(t, settings.value)}
                  loading={стартует === 'settings'}
                  disabled={!!стартует}
                  onClick={() => void начать('settings')}
                />
              )}
              <Старт
                title={t('cards.set.startWrong')}
                hint={t('cards.set.startWrongHint')}
                loading={стартует === 'wrong'}
                disabled={!!стартует}
                onClick={() => void начать('wrong')}
              />
              <Старт
                title={t('cards.set.startAll')}
                hint={t('cards.set.startAllHint')}
                loading={стартует === 'all_file'}
                disabled={!!стартует}
                onClick={() => void начать('all_file')}
              />
            </div>
            {пустойЗаход && (
              <p role="status" className="m-0 text-sm text-warn">
                {t('cards.set.emptySession')}
              </p>
            )}
          </section>

          <section aria-labelledby="set-topics" className="flex flex-col gap-s3">
            <h2 id="set-topics" className="m-0 font-display text-lg font-semibold text-ink-strong">
              {t('cards.set.topics')}
            </h2>
            {data.topics.length === 0 ? (
              <p className="m-0 text-sm text-muted">{t('cards.set.noTopics')}</p>
            ) : (
              <ul className="m-0 flex list-none flex-col divide-y divide-line overflow-hidden rounded-md border border-line bg-surface p-0 shadow-1">
                {строкиТем.map((row) => {
                  const p = knownPercent(row.known, row.total)
                  return (
                    <li key={row.id}>
                      <button
                        type="button"
                        aria-pressed={тема === row.id}
                        onClick={() => выбратьТему(тема === row.id ? '' : row.id)}
                        className={cn(
                          'flex min-h-[52px] w-full flex-col gap-1.5 px-s4 py-s2 text-left hover:bg-surface-2',
                          'focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent',
                          тема === row.id && 'bg-accent-bg',
                        )}
                      >
                        <span className="flex items-baseline justify-between gap-s3">
                          <span className={cn('min-w-0 break-words text-sm font-medium text-ink-strong', row.id === NO_TOPIC && 'italic')}>
                            {row.title}
                          </span>
                          <span className="shrink-0 font-mono text-xs text-muted">
                            {row.known}/{row.total} · {p}%
                          </span>
                        </span>
                        <Progress value={p / 100} tone={p === 100 ? 'ok' : 'accent'} label={row.title} />
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>
        </div>

        {!isPhone && панельНастроек}
      </div>

      <CardsList
        ref={список}
        projectId={projectId}
        setId={setId}
        topics={data.topics}
        hasNoTopic={естьБезТемы}
        topic={тема}
        onTopic={setТема}
      />

      {settings.defaultsError && <p className="m-0 text-sm text-err">{errorText(settings.defaultsError)}</p>}

      {isPhone && (
        <div className="sticky bottom-0 z-10 -mx-s3 -mb-s3 border-t border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] px-s3 pt-s2 pb-[max(env(safe-area-inset-bottom),var(--space-2))] backdrop-blur-theme">
          <Button
            variant="primary"
            size="lg"
            className="w-full"
            loading={стартует === 'settings'}
            disabled={!!стартует && стартует !== 'settings'}
            onClick={() => void начать('settings')}
          >
            {t('cards.set.startSettings')}
          </Button>
        </div>
      )}

      {canEdit && (
        <>
          <ReplaceDialog open={диалог === 'replace'} onOpenChange={(o) => setДиалог(o ? 'replace' : null)} projectId={projectId} setId={setId} />
          <RenameDialog
            open={диалог === 'rename'}
            onOpenChange={(o) => setДиалог(o ? 'rename' : null)}
            projectId={projectId}
            setId={setId}
            title={data.title}
            description={data.description}
          />
          <DeleteDialog
            open={диалог === 'delete'}
            onOpenChange={(o) => setДиалог(o ? 'delete' : null)}
            projectId={projectId}
            setId={setId}
            title={data.title}
            onDeleted={() => navigate(cardsPaths.library, { replace: true })}
          />
        </>
      )}
    </div>
  )
}

/** Кнопка быстрого старта: название и подсказка под ним. */
function Старт({
  title,
  hint,
  primary = false,
  loading,
  disabled,
  onClick,
}: {
  title: string
  hint?: string
  primary?: boolean
  loading?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <Button
      variant={primary ? 'primary' : 'secondary'}
      size="lg"
      loading={loading}
      disabled={disabled && !loading}
      onClick={onClick}
      className="h-auto min-h-[56px] min-w-0 flex-col items-start justify-center gap-0.5 whitespace-normal py-s2 text-left"
    >
      <span className="text-sm font-semibold">{title}</span>
      {hint && <span className="line-clamp-2 text-xs font-normal opacity-80">{hint}</span>}
    </Button>
  )
}

/**
 * Мои настройки набора: значение на экране, запись с задержкой, дописывание перед
 * стартом и при уходе со страницы.
 */
function useSetSettings(projectId: string, setId: string, data: CardSet | undefined) {
  const t = useT()
  const put = usePutMySettings()
  const putDefaults = usePutDefaults()
  const [своё, setСвоё] = useState<CardSettings | null>(null)
  const очередь = useRef<CardSettings | null>(null)
  const таймер = useRef<number | null>(null)

  const defaults = settingsOf(data?.defaults)
  const value = своё ?? (data?.my_settings ? settingsOf(data.my_settings, defaults) : defaults)

  const { mutateAsync } = put
  const flush = useCallback(async () => {
    if (таймер.current !== null) {
      window.clearTimeout(таймер.current)
      таймер.current = null
    }
    const s = очередь.current
    очередь.current = null
    if (s) await mutateAsync({ projectId, setId, settings: s })
  }, [mutateAsync, projectId, setId])

  const change = useCallback(
    (next: CardSettings) => {
      setСвоё(next)
      очередь.current = next
      if (таймер.current !== null) window.clearTimeout(таймер.current)
      таймер.current = window.setTimeout(() => {
        flush().catch(() => {
          // Беда видна под панелью (`put.error`); следующая правка попробует снова.
        })
      }, 600)
    },
    [flush],
  )

  // Уход со страницы с незаписанной правкой — дописываем её.
  useEffect(() => {
    const ждёт = очередь
    const часы = таймер
    return () => {
      if (часы.current !== null) window.clearTimeout(часы.current)
      const s = ждёт.current
      ждёт.current = null
      if (s) void putMySettings(projectId, setId, s).catch(() => {})
    }
  }, [projectId, setId])

  // Другой набор — своё значение с прошлого набора не переносится.
  useEffect(() => {
    setСвоё(null)
  }, [projectId, setId])

  return {
    value,
    defaults,
    change,
    flush,
    saving: put.isPending,
    error: put.isError ? `${t('cards.settings.saveFailed')} ${errorText(put.error)}` : null,
    makeDefault: () => putDefaults.mutate({ projectId, setId, settings: value }),
    makingDefault: putDefaults.isPending,
    defaultsError: putDefaults.isError ? putDefaults.error : null,
  }
}
