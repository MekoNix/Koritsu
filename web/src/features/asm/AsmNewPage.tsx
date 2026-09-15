/**
 * AsmNewPage — новая программа: режим, версия инструментов, имя.
 *
 *     /asm/new?toolchain=mingw64
 *
 * Режим выбирается здесь один раз: исходник TASM не соберётся `as`, и у готовой
 * программы режим не меняется. Карточки режимов — из `GET /api/asm/status`
 * (`toolchains`): служба называет только включённые на машине режимы, подписи
 * к ним — словарь сайта. `?toolchain=` предвыбирает карточку (так приходят из
 * фильтра списка и из «Файл → Новая программа»).
 *
 * Версия показывается выбором, только если у режима их больше одной. Режим, для
 * которого на сервере нет инструментов, выбрать можно — писать исходник это не
 * мешает, — но под карточками стоит предупреждение, как полоса в списке.
 *
 * «Создать» ведёт сразу в редактор программы; пример исходника режима кладёт
 * страница программы при первом открытии.
 */
import { useState, type KeyboardEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { BetaTag, Button, EmptyState, ErrorState, Icon, Input, Select, SkeletonLines } from '@/ui'
import { canEditWorkspace } from '@/features/projects/data'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { useAsmStatus, useCreateAsmProgram } from './api'
import { isToolchainId, TOOLCHAIN_BETA, TOOLCHAIN_IDS } from './toolchains'
import type { AsmToolchainId, AsmToolchainStatus } from './types'

export function AsmNewPage() {
  const t = useT()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const workspace = useCurrentWorkspace()
  const status = useAsmStatus()
  const create = useCreateAsmProgram()
  useDocumentCrumb(t('asm.new.title'))

  const wanted = params.get('toolchain')
  const [chosen, setChosen] = useState<AsmToolchainId | null>(isToolchainId(wanted) ? wanted : null)
  const [versions, setVersions] = useState<Partial<Record<AsmToolchainId, string>>>({})
  const [name, setName] = useState('')

  const modes = [...(status.data?.toolchains ?? [])].sort((a, b) => TOOLCHAIN_IDS.indexOf(a.id) - TOOLCHAIN_IDS.indexOf(b.id))
  const mode = modes.find((m) => m.id === chosen) ?? modes[0]
  const version = mode ? (versions[mode.id] ?? mode.default_version) : ''
  const canEdit = canEditWorkspace(workspace.data?.role)

  const submit = () => {
    const ws = workspace.data?.id
    if (!ws || !mode || create.isPending) return
    create.mutate(
      { workspaceId: ws, name: name.trim(), toolchain: mode.id, ...(version ? { toolchainVersion: version } : {}) },
      { onSuccess: (p) => navigate(`/asm/${p.project_id}/${p.program_id}`, { replace: true }) },
    )
  }

  // Стрелки по карточкам — как по радиокнопкам: группа одна, выбор идёт за фокусом.
  const onCardKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!d || !modes.length) return
    e.preventDefault()
    const next = modes[(i + d + modes.length) % modes.length]!
    setChosen(next.id)
    const group = e.currentTarget.parentElement
    requestAnimationFrame(() => group?.querySelector<HTMLButtonElement>(`[data-toolchain="${next.id}"]`)?.focus())
  }

  let body
  if (status.isPending || workspace.isPending) body = <SkeletonLines count={4} />
  else if (status.isError) body = <ErrorState error={status.error} onRetry={() => void status.refetch()} />
  else if (!mode) body = <EmptyState icon="queue" title={t('asm.new.noModes')} />
  else if (!canEdit) body = <EmptyState icon="queue" title={t('asm.new.forbidden')} />
  else
    body = (
      <form
        className="flex max-w-[760px] flex-col gap-s4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div
          role="radiogroup"
          aria-label={t('asm.new.mode')}
          className="grid gap-s3 [grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]"
        >
          {modes.map((m, i) => (
            <ModeCard key={m.id} mode={m} selected={m.id === mode.id} onSelect={() => setChosen(m.id)} onKeyDown={(e) => onCardKey(e, i)} />
          ))}
        </div>

        {!mode.available && (
          <div className="flex items-start gap-s2 rounded-md border border-warn bg-warn-bg px-s4 py-s3 text-sm text-ink">
            <Icon name="warning" size={16} className="mt-0.5 text-warn" />
            <span>{t('asm.new.unavailable')}</span>
          </div>
        )}

        {mode.versions.length > 1 && (
          <Select
            label={t('asm.new.version')}
            value={version}
            className="max-w-[420px]"
            onChange={(e) => setVersions((was) => ({ ...was, [mode.id]: e.target.value }))}
          >
            {mode.versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.available ? v.title : `${v.title} · ${t('asm.new.versionMissing')}`}
              </option>
            ))}
          </Select>
        )}

        <Input
          label={t('asm.new.name')}
          placeholder={t('asm.new.namePlaceholder')}
          value={name}
          maxLength={120}
          className="max-w-[420px]"
          onChange={(e) => setName(e.target.value)}
        />

        {create.isError && <p className="text-sm text-err">{errorText(create.error)}</p>}

        <div className="flex flex-wrap items-center gap-s2">
          <Button variant="primary" type="submit" loading={create.isPending}>
            <Icon name="plus" size={16} />
            {t('asm.new.create')}
          </Button>
          <Link to="/asm" className="text-sm text-muted hover:text-ink">
            {t('asm.new.back')}
          </Link>
        </div>
      </form>
    )

  return (
    <div className="flex flex-col gap-s5">
      <header className="min-w-0">
        <WorkspaceCaption ws={workspace.data} className="mb-1" />
        <h1 className="flex items-center gap-s2 font-display text-2xl font-semibold text-ink-strong">
          {t('asm.new.title')}
          <BetaTag label={t('shell.beta')} />
        </h1>
        <p className="max-w-[64ch] text-sm text-muted">{t('asm.new.subtitle')}</p>
      </header>
      {body}
    </div>
  )
}

function ModeCard({
  mode,
  selected,
  onSelect,
  onKeyDown,
}: {
  mode: AsmToolchainStatus
  selected: boolean
  onSelect: () => void
  onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void
}) {
  const t = useT()
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      tabIndex={selected ? 0 : -1}
      data-toolchain={mode.id}
      onClick={onSelect}
      onKeyDown={onKeyDown}
      className={cn(
        'flex h-full flex-col items-start gap-s2 rounded-md border bg-surface p-s4 text-left shadow-1',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        selected ? 'border-accent ring-[3px] ring-accent-bg' : 'border-line hover:border-line-strong',
      )}
    >
      <span className="flex items-center gap-s2 font-semibold text-ink-strong">
        <Icon name="queue" size={16} style={{ color: 'var(--mod-asm)' }} />
        {t(`asm.toolchain.${mode.id}.title`)}
        {TOOLCHAIN_BETA[mode.id] && <BetaTag label={t('shell.beta')} />}
      </span>
      <span className="text-sm text-muted">{t(`asm.toolchain.${mode.id}.text`)}</span>
      <span className="mt-auto flex flex-wrap items-center gap-s2 font-mono text-xs text-muted">
        {mode.versions.find((v) => v.id === mode.default_version)?.title ?? mode.default_version}
        {!mode.available && <span className="font-sans text-warn">· {t('asm.new.unavailableShort')}</span>}
      </span>
    </button>
  )
}
