/**
 * BoardListPage — главная модуля «Доска»: доски текущего пространства списком.
 *
 * **Работы здесь нет ни одной.** Доска на томе по-прежнему решение работы — у
 * неё своя папка файлов, своё условие и своя лента прогонов, — но выбирать
 * работу человеку незачем: доску заводят, чтобы решить задачу, а не чтобы
 * завести папку. Поэтому список плоский, «Новая доска» — одно нажатие, а работу,
 * в которую доска легла, находит служба (`POST /api/board/boards`).
 *
 * **Доска принадлежит пространству, а не браузеру.** Сцена, оставленная в
 * браузере, теряется вместе с вкладкой и не доезжает до второго устройства — а
 * доску открывают с планшета, на котором пишут, и с ноутбука, на котором
 * смотрят. Отсюда и подпись пространства в заголовке: пропавшую доску иначе
 * ищут здесь, а она в соседнем пространстве.
 *
 * **Прогон отсюда не запускается.** «Новая доска» заводит запись и каталог и
 * ведёт на экран доски; платный прогон начинается там — после того, как на доске
 * появилась хоть одна подтверждённая строка.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, Dialog, EmptyState, ErrorState, Icon, Input, SkeletonLines } from '@/ui'
import { canEditWorkspace } from '@/features/projects/data'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { useCreateWorkspaceBoard, useDeleteBoard, useWorkspaceBoards } from './data'
import type { WorkspaceBoardCard } from './types'

export function BoardListPage() {
  const t = useT()
  const navigate = useNavigate()
  const workspace = useCurrentWorkspace()
  const boards = useWorkspaceBoards(workspace.data?.id)
  const создать = useCreateWorkspaceBoard()
  const удалить = useDeleteBoard()

  const [query, setQuery] = useState('')
  const [сносим, setСносим] = useState<WorkspaceBoardCard | null>(null)

  const canEdit = canEditWorkspace(workspace.data?.role)

  const найденные = useMemo(() => {
    const запрос = query.trim().toLowerCase()
    if (!запрос) return boards.data ?? []
    return (boards.data ?? []).filter(
      (доска) =>
        имя(доска, t).toLowerCase().includes(запрос) ||
        // Поиск идёт и по работе, хотя её нигде не видно: доску, заведённую со
        // страницы работы, человек помнит по этой работе, а не по имени,
        // которого он ей не давал.
        доска.project_name.toLowerCase().includes(запрос),
    )
  }, [boards.data, query, t])

  function завестиДоску() {
    const ws = workspace.data?.id
    if (!ws) return
    создать.mutate(
      { workspaceId: ws },
      { onSuccess: (доска) => navigate(`/board/${доска.project_id}/${доска.id}`) },
    )
  }

  const кнопка = canEdit ? (
    <Button variant="primary" loading={создать.isPending} onClick={завестиДоску}>
      <Icon name="plus" size={16} />
      {t('board.home.create')}
    </Button>
  ) : null

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <WorkspaceCaption ws={workspace.data} className="mb-1" />
          <h1 className="font-display text-2xl font-semibold text-ink-strong">
            {t('board.home.title')}
          </h1>
          <p className="max-w-[64ch] text-sm text-muted">{t('board.home.subtitle')}</p>
        </div>
        {кнопка}
      </header>

      {создать.isError && <p className="text-sm text-err">{errorText(создать.error)}</p>}

      {boards.isPending ? (
        <SkeletonLines count={4} />
      ) : boards.isError ? (
        <ErrorState error={boards.error} onRetry={() => void boards.refetch()} />
      ) : (boards.data ?? []).length === 0 ? (
        <EmptyState
          icon="board"
          title={t('board.home.emptyTitle')}
          text={t('board.home.emptyText')}
          action={кнопка}
        />
      ) : (
        <>
          <Input
            value={query}
            className="max-w-[420px]"
            placeholder={t('board.home.search')}
            aria-label={t('board.home.search')}
            onChange={(e) => setQuery(e.target.value)}
          />
          {найденные.length === 0 ? (
            <EmptyState icon="board" title={t('board.home.nothingFound')} />
          ) : (
            <ul
              className="grid gap-s3 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]"
              data-testid="board-list"
            >
              {найденные.map((доска) => (
                <li key={доска.id}>
                  <article className="flex h-full flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
                    <Link
                      to={`/board/${доска.project_id}/${доска.id}`}
                      className="flex items-center gap-s2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      <Icon name="board" size={16} style={{ color: 'var(--mod-board)' }} />
                      <span className="truncate font-semibold text-ink-strong">
                        {имя(доска, t)}
                      </span>
                    </Link>
                    <span className="mt-auto flex flex-wrap items-center gap-s2 text-xs text-muted">
                      <span>{t('board.home.lines', { n: доска.steps })}</span>
                      {доска.created_at && <span>{когда(доска.created_at)}</span>}
                      {доска.checked_at && <span>{t('board.home.checked')}</span>}
                      {canEdit && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="ml-auto"
                          aria-label={`${t('board.home.delete')} ${имя(доска, t)}`}
                          onClick={() => setСносим(доска)}
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

      {/* Подтверждение своим окном, а не `confirm()` браузера: окно называет
          доску по имени и перечисляет, что именно уходит вместе с ней. */}
      <Dialog
        open={!!сносим}
        onOpenChange={(открыто) => !открыто && setСносим(null)}
        title={t('board.home.deleteTitle', { name: сносим ? имя(сносим, t) : '' })}
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
                  { projectId: сносим.project_id, boardId: сносим.id },
                  { onSuccess: () => setСносим(null) },
                )
              }
            >
              {t('board.home.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('board.home.deleteHint')}</p>
      </Dialog>
    </div>
  )
}

/** Имя доски: своё, если дали, иначе «Доска N» — номер считает служба. */
function имя(
  доска: WorkspaceBoardCard,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  return доска.name || t('board.home.boardName', { n: доска.n })
}

/** Время человеку: дата и часы, без секунд. */
function когда(iso: string | null | undefined): string {
  if (!iso) return ''
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
