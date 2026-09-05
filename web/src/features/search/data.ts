/**
 * data — что палитра ищет.
 *
 * Поиска у службы нет: `GET /api/projects` берёт одно пространство и не знает
 * слова «запрос», а материалы отдаются описью работы. Поэтому палитра ищет по
 * тому, что уже загружено:
 *
 * * **проекты всех пространств** — список пространств, затем список проектов
 *   каждого (тот же приём, что у главной страницы схем);
 * * **материалы открытой работы** — по описи того проекта, чей адрес открыт.
 *
 * Материалы всех работ сразу не берутся намеренно: это по запросу на работу, то
 * есть десятки запросов ради подсказки. Правильное лекарство — поиск на стороне
 * службы; пока его нет, честнее искать по тому, что человек и так видит.
 *
 * Запросы ленивые: пока палитра закрыта, ни одного обращения к службе нет.
 */
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { api, keys, unwrap } from '@/api'
import type { Workspace } from '@/api/hooks'
import type { Material, Project } from '@/features/projects/types'
import { workspaceLabel } from '@/features/workspace/types'

import type { Hit } from './filter'

type ПроектСПространством = Project & { workspaceName: string }

async function всеПроекты(personalText: string): Promise<ПроектСПространством[]> {
  const { workspaces } = await unwrap<{ workspaces: Workspace[] }>(api.GET('/api/workspaces'))
  const пачки = await Promise.all(
    workspaces.map((ws) =>
      unwrap<{ projects: Project[] }>(
        api.GET('/api/projects', { params: { query: { workspace_id: ws.id } } }),
      ).then((тело) =>
        тело.projects.map((p) => ({ ...p, workspaceName: workspaceLabel(ws, personalText) })),
      ),
    ),
  )
  return пачки.flat()
}

/**
 * Всё, по чему палитра ищет, одним списком.
 *
 * `enabled` — это открыта ли палитра: закрытая палитра службу не беспокоит.
 */
export function useSearchIndex(
  enabled: boolean,
  projectId: string | null,
  /** Как назвать личное пространство: перевод знает экран, не этот файл. */
  personalText: string,
): {
  hits: Hit[]
  isLoading: boolean
  error: unknown
} {
  const проекты = useQuery({
    queryKey: keys.search.projects,
    enabled,
    queryFn: () => всеПроекты(personalText),
    staleTime: 30_000,
  })

  const материалы = useQuery({
    queryKey: keys.search.materials(projectId ?? ''),
    enabled: enabled && !!projectId,
    queryFn: () =>
      unwrap<Material[]>(
        api.GET('/api/projects/{project_id}/materials', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
    staleTime: 30_000,
  })

  const hits = useMemo<Hit[]>(() => {
    const проектные: Hit[] = (проекты.data ?? []).map((p) => ({
      kind: 'project',
      id: p.id,
      name: p.name,
      workspace: p.workspaceName,
      to: `/projects/${p.id}`,
    }))
    const имяРаботы = (проекты.data ?? []).find((p) => p.id === projectId)?.name ?? ''
    const файлы: Hit[] = projectId
      ? (материалы.data ?? []).map((m) => ({
          kind: 'material',
          id: m.id,
          name: m.name,
          project: имяРаботы,
          // Материалы живут в описи работы — туда и ведём.
          to: `/projects/${projectId}`,
        }))
      : []
    return [...проектные, ...файлы]
  }, [проекты.data, материалы.data, projectId])

  return {
    hits,
    isLoading: проекты.isLoading || материалы.isLoading,
    error: проекты.error ?? материалы.error,
  }
}
