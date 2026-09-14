/**
 * AsmListPage — главная модуля «Ассемблер»: программы текущего пространства.
 *
 * Как у доски: работы здесь не видно. Программа на томе — решение работы, но
 * выбирать работу незачем: программу заводят, чтобы написать и прогнать код, и
 * «Новая программа» — одно нажатие, после которого сразу открывается редактор.
 *
 * Если на машине службы нет TASM, TLINK, DOSBox-X или DebugX, список всё равно
 * показывается — писать исходник можно и так, — но полосой сверху сказано, что
 * собрать его сейчас не выйдет. Узнать это после нажатия «Собрать» было бы
 * обиднее.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useT } from '@/i18n'
import { BetaTag, Button, Chip, Dialog, EmptyState, ErrorState, Icon, Input, SkeletonLines } from '@/ui'
import { canEditWorkspace } from '@/features/projects/data'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import {
  useAsmPrograms,
  useAsmStatus,
  useCreateAsmProgram,
  useDeleteAsmProgram,
  type AsmProgramCard,
} from './api'

export function AsmListPage() {
  const t = useT()
  const navigate = useNavigate()
  const workspace = useCurrentWorkspace()
  const programs = useAsmPrograms(workspace.data?.id)
  const status = useAsmStatus()
  const создать = useCreateAsmProgram()
  const удалить = useDeleteAsmProgram()
  const [query, setQuery] = useState('')
  const [сносим, setСносим] = useState<AsmProgramCard | null>(null)
  const canEdit = canEditWorkspace(workspace.data?.role)

  const найденные = useMemo(() => {
    const q = query.trim().toLowerCase()
    const все = programs.data ?? []
    return q ? все.filter((p) => имя(p, t).toLowerCase().includes(q)) : все
  }, [programs.data, query, t])

  function завести() {
    const ws = workspace.data?.id
    if (!ws) return
    создать.mutate({ workspaceId: ws }, { onSuccess: (p) => navigate(`/asm/${p.project_id}/${p.program_id}`) })
  }

  const кнопка = canEdit ? (
    <Button variant="primary" loading={создать.isPending} onClick={завести}>
      <Icon name="plus" size={16} />
      {t('asm.list.create')}
    </Button>
  ) : null

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <WorkspaceCaption ws={workspace.data} className="mb-1" />
          <h1 className="flex items-center gap-s2 font-display text-2xl font-semibold text-ink-strong">
            {t('asm.title')}
            <BetaTag label={t('shell.beta')} />
          </h1>
          <p className="max-w-[64ch] text-sm text-muted">{t('asm.list.subtitle')}</p>
        </div>
        {кнопка}
      </header>

      {status.data && !status.data.available && (
        <div className="flex items-start gap-s2 rounded-md border border-warn bg-warn-bg px-s4 py-s3 text-sm text-ink">
          <Icon name="warning" size={16} className="mt-0.5 text-warn" />
          <span>{t('asm.list.unavailable')}</span>
        </div>
      )}

      {создать.isError && <p className="text-sm text-err">{errorText(создать.error)}</p>}

      {programs.isPending ? (
        <SkeletonLines count={4} />
      ) : programs.isError ? (
        <ErrorState error={programs.error} onRetry={() => void programs.refetch()} />
      ) : (programs.data ?? []).length === 0 ? (
        <EmptyState icon="queue" title={t('asm.list.emptyTitle')} text={t('asm.list.emptyText')} action={кнопка} />
      ) : (
        <>
          <Input
            value={query}
            className="max-w-[420px]"
            placeholder={t('asm.list.search')}
            aria-label={t('asm.list.search')}
            onChange={(e) => setQuery(e.target.value)}
          />
          {найденные.length === 0 ? (
            <EmptyState icon="queue" title={t('asm.list.nothingFound')} />
          ) : (
            <ul className="grid gap-s3 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]">
              {найденные.map((p) => (
                <li key={p.program_id}>
                  <article className="flex h-full flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
                    <Link
                      to={`/asm/${p.project_id}/${p.program_id}`}
                      className="flex items-center gap-s2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      <Icon name="queue" size={16} style={{ color: 'var(--mod-asm)' }} />
                      <span className="truncate font-mono font-semibold text-ink-strong">{имя(p, t)}</span>
                    </Link>
                    <span className="mt-auto flex flex-wrap items-center gap-s2 text-xs text-muted">
                      {p.last_status && <Chip>{t(`asm.list.last.${p.last_status}`)}</Chip>}
                      {p.updated_at && <span>{когда(p.updated_at)}</span>}
                      {canEdit && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="ml-auto"
                          aria-label={`${t('asm.list.delete')} ${имя(p, t)}`}
                          onClick={() => setСносим(p)}
                        >
                          {t('common.action.delete')}
                        </Button>
                      )}
                    </span>
                  </article>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {удалить.isError && <p className="text-sm text-err">{errorText(удалить.error)}</p>}

      <Dialog
        open={!!сносим}
        onOpenChange={(открыто) => !открыто && setСносим(null)}
        title={t('asm.list.deleteTitle', { name: сносим ? имя(сносим, t) : '' })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setСносим(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={удалить.isPending}
              onClick={() =>
                сносим &&
                удалить.mutate(
                  { projectId: сносим.project_id, programId: сносим.program_id },
                  { onSuccess: () => setСносим(null) },
                )
              }
            >
              {t('asm.list.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('asm.list.deleteHint')}</p>
      </Dialog>
    </div>
  )
}

function имя(p: AsmProgramCard, t: (key: string, vars?: Record<string, string | number>) => string): string {
  return p.name || t('asm.list.untitled')
}

function когда(iso: string): string {
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}
