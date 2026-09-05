/**
 * data — запросы области «Задания» одним файлом.
 *
 * То же правило, что у соседних областей: адрес маршрута, форма ответа и
 * список ключей, которые сбрасываются после изменения, — одно знание и живёт в
 * одном месте. Экраны зовут хуки, а не `api.GET`.
 *
 * Общее с областью «Проекты» (карточка проекта, материалы, постановка задания,
 * адрес артефакта) берётся из `@/features/projects/data` и здесь не
 * повторяется: второй `useProject` рядом с первым — это два кэша одного
 * проекта, которые расходятся после переименования.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'

import type { Wishes } from './stages'
import type {
  BlockRecordBody,
  BlockVersionBody,
  BlockVersionHead,
  BlockVersionsBody,
  BlocksBody,
  KadaiStatus,
  StageNamesBody,
} from './types'

/**
 * Имена семи стадий по порядку.
 *
 * Списком от службы, а не константой в браузере: своя копия отстала бы от
 * пакета молча — восьмая стадия появилась бы в службе и не появилась бы на
 * экране. Список один на всю службу и не меняется, отсюда долгий `staleTime`.
 */
export function useStageNames(): UseQueryResult<string[]> {
  return useQuery({
    queryKey: keys.kadai.stageNames,
    queryFn: async () => (await unwrap<StageNamesBody>(api.GET('/api/kadai/stages'))).stages,
    staleTime: 60 * 60_000,
  })
}

/**
 * Ход работы: стадии, остановка с вопросом, распознанное условие, файлы.
 *
 * Читается это без модели и без стадий, поэтому опрашивать снимок дёшево. Пока
 * идёт прогон, ход показывают события потока (`stages.mergeStages`), а снимок
 * перечитывается на конце задания — второй способ узнать то же самое раз в
 * секунду был бы запросом на каждое событие.
 */
export function useKadaiStatus(projectId: string | undefined): UseQueryResult<KadaiStatus> {
  return useQuery({
    queryKey: keys.kadai.status(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<KadaiStatus>(
        api.GET('/api/projects/{project_id}/kadai', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

/**
 * Назвать материал условием задачи.
 *
 * Без этого прогон отказывает «условие задачи не приложено»: до подтверждения
 * условие — обычный материал.
 */
export function useSetCondition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, materialId }: { projectId: string; materialId: string }) =>
      unwrap<{ condition: string | null }>(
        api.PUT('/api/projects/{project_id}/kadai/condition', {
          params: { path: { project_id: projectId } },
          body: { material_id: materialId },
        }),
      ),
    onSuccess: (_answer, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.kadai.status(projectId) })
    },
  })
}

/**
 * Пожелания к работе — из проекта, а не из браузера.
 *
 * Раньше они лежали в `sessionStorage`: службе негде было их держать до
 * первого прогона, потому что записи о работе тогда ещё нет. Теперь у них своя
 * запись на томе (`PUT …/kadai/wishes`), и они переживают и вкладку, и второе
 * устройство. Читает их прогон сам, когда в задании пожеланий нет.
 */
export function useKadaiWishes(projectId: string | undefined): UseQueryResult<Wishes> {
  return useQuery({
    queryKey: keys.kadai.wishes(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<Wishes>(
        api.GET('/api/projects/{project_id}/kadai/wishes', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

/**
 * Записать пожелания. Заменяются целиком: половины у них не бывает.
 *
 * Проект называется в самом вызове, а не при заведении хука (как у
 * `useSetCondition`): форма заведения работы записывает пожелания в проект,
 * который только что создала, и её `useState` к этой секунде ещё не обновился —
 * замыкание на прежнее значение положило бы их в никуда.
 */
export function useSetKadaiWishes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, wishes }: { projectId: string; wishes: Wishes }) =>
      unwrap<Wishes>(
        api.PUT('/api/projects/{project_id}/kadai/wishes', {
          params: { path: { project_id: projectId } },
          body: wishes,
        }),
      ),
    onSuccess: (_ответ, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.kadai.wishes(projectId) })
    },
  })
}

/**
 * «Начать стадию заново» у вставшей работы.
 *
 * Ничего не стоит и модель не зовёт: маршрут только возвращает ход работы к
 * названной стадии. Прогон после него ставится обычным `kadai_run` — тем же,
 * которым работа запускалась в первый раз, и это единственное место, где
 * начинается платный прогон.
 */
export function useRestartKadai(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (stage?: string) =>
      unwrap<KadaiStatus & { restarted: string }>(
        api.POST('/api/projects/{project_id}/kadai/restart', {
          params: { path: { project_id: projectId as string } },
          body: { stage: stage ?? '' },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.kadai.status(projectId ?? '') })
    },
  })
}

/** Блоки работы в порядке документа. Пусто — списка ещё не заводили. */
export function useBlocks(projectId: string | undefined): UseQueryResult<BlockRecordBody[]> {
  return useQuery({
    queryKey: keys.kadai.blocks(projectId ?? ''),
    enabled: !!projectId,
    queryFn: async () =>
      (
        await unwrap<BlocksBody>(
          api.GET('/api/projects/{project_id}/blocks', {
            params: { path: { project_id: projectId as string } },
          }),
        )
      ).blocks,
  })
}

/**
 * Версии списка блоков. Список версионируется целиком, а не поблочно: половина
 * правок переставляет блоки местами, и поблочная версия об этом молчит.
 */
export function useBlockVersions(
  projectId: string | undefined,
): UseQueryResult<BlockVersionHead[]> {
  return useQuery({
    queryKey: keys.kadai.blockVersions(projectId ?? ''),
    enabled: !!projectId,
    queryFn: async () =>
      (
        await unwrap<BlockVersionsBody>(
          api.GET('/api/projects/{project_id}/blocks/versions', {
            params: { path: { project_id: projectId as string } },
          }),
        )
      ).versions,
    retry: false,
  })
}

/** Одна версия списка целиком: шапка и блоки, какими они были. */
export function useBlockVersion(
  projectId: string | undefined,
  n: number | null,
): UseQueryResult<BlockVersionBody> {
  return useQuery({
    queryKey: keys.kadai.blockVersion(projectId ?? '', n ?? 0),
    enabled: !!projectId && n !== null,
    queryFn: () =>
      unwrap<BlockVersionBody>(
        api.GET('/api/projects/{project_id}/blocks/versions/{n}', {
          params: { path: { project_id: projectId as string, n: n as number } },
        }),
      ),
    retry: false,
  })
}

/**
 * Вернуть прошлую версию списка.
 *
 * Возврат ничего не удаляет: служба дописывает выбранный список новой версией,
 * и номер в ответе БОЛЬШЕ того, к которому вернулись (`versions/routes.py`).
 * Поэтому и список версий, и сами блоки после возврата обязаны перечитаться.
 */
export function useRollbackBlocks(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (n: number) =>
      unwrap<{ version: BlockVersionHead; restored_from: number }>(
        api.POST('/api/projects/{project_id}/blocks/rollback', {
          params: { path: { project_id: projectId as string } },
          body: { n },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.kadai.blocks(projectId ?? '') })
      void qc.invalidateQueries({ queryKey: keys.kadai.blockVersions(projectId ?? '') })
    },
  })
}
