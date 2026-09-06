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
 *
 * **Почти каждый хук берёт `runId`.** Решений в работе несколько, у каждого
 * своё условие, свои пожелания, свой ход стадий и свой список блоков; служба
 * различает их параметром `run`, и хук, который его не передаёт, показал бы на
 * экране одного решения ответ, полученный для другого. Пустая строка — работа
 * целиком, какой её видели, пока решение в ней было одно.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'
import { СВЕЖЕСТЬ_ПОД_ПОТОКОМ } from '@/features/projects/data'
import type { Material } from '@/features/projects/types'

import type { Wishes } from './stages'
import type {
  BlockRecordBody,
  BlockVersionBody,
  BlockVersionHead,
  BlockVersionsBody,
  BlocksBody,
  KadaiRunCard,
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
export function useKadaiStatus(
  projectId: string | undefined,
  runId = '',
): UseQueryResult<KadaiStatus> {
  return useQuery({
    queryKey: keys.kadai.status(projectId ?? '', runId),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<KadaiStatus>(
        api.GET('/api/projects/{project_id}/kadai', {
          params: { path: { project_id: projectId as string }, query: { run: runId } },
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
    mutationFn: ({
      projectId,
      materialId,
      runId = '',
    }: {
      projectId: string
      materialId: string
      runId?: string
    }) =>
      unwrap<{ condition: string | null }>(
        api.PUT('/api/projects/{project_id}/kadai/condition', {
          params: { path: { project_id: projectId }, query: { run: runId } },
          body: { material_id: materialId },
        }),
      ),
    onSuccess: (_answer, { projectId, runId = '' }) => {
      void qc.invalidateQueries({ queryKey: keys.kadai.status(projectId, runId) })
      // Условие — карточка решения в списке: пока его не назвали, карточка
      // молчит о том, какую задачу решают.
      void qc.invalidateQueries({ queryKey: keys.kadai.runs(projectId) })
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
export function useKadaiWishes(projectId: string | undefined, runId = ''): UseQueryResult<Wishes> {
  return useQuery({
    queryKey: keys.kadai.wishes(projectId ?? '', runId),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<Wishes>(
        api.GET('/api/projects/{project_id}/kadai/wishes', {
          params: { path: { project_id: projectId as string }, query: { run: runId } },
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
    mutationFn: ({
      projectId,
      wishes,
      runId = '',
    }: {
      projectId: string
      wishes: Wishes
      runId?: string
    }) =>
      unwrap<Wishes>(
        api.PUT('/api/projects/{project_id}/kadai/wishes', {
          params: { path: { project_id: projectId }, query: { run: runId } },
          body: wishes,
        }),
      ),
    onSuccess: (_ответ, { projectId, runId = '' }) => {
      void qc.invalidateQueries({ queryKey: keys.kadai.wishes(projectId, runId) })
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
export function useRestartKadai(projectId: string | undefined, runId = '') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (stage?: string) =>
      unwrap<KadaiStatus & { restarted: string }>(
        api.POST('/api/projects/{project_id}/kadai/restart', {
          params: { path: { project_id: projectId as string }, query: { run: runId } },
          body: { stage: stage ?? '' },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.kadai.status(projectId ?? '', runId) })
    },
  })
}

/** Блоки работы в порядке документа. Пусто — списка ещё не заводили. */
export function useBlocks(
  projectId: string | undefined,
  runId = '',
): UseQueryResult<BlockRecordBody[]> {
  return useQuery({
    queryKey: keys.kadai.blocks(projectId ?? '', runId),
    enabled: !!projectId,
    queryFn: async () =>
      (
        await unwrap<BlocksBody>(
          api.GET('/api/projects/{project_id}/blocks', {
            params: { path: { project_id: projectId as string }, query: { run: runId } },
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
  runId = '',
): UseQueryResult<BlockVersionHead[]> {
  return useQuery({
    queryKey: keys.kadai.blockVersions(projectId ?? '', runId),
    enabled: !!projectId,
    queryFn: async () =>
      (
        await unwrap<BlockVersionsBody>(
          api.GET('/api/projects/{project_id}/blocks/versions', {
            params: { path: { project_id: projectId as string }, query: { run: runId } },
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
  runId = '',
): UseQueryResult<BlockVersionBody> {
  return useQuery({
    queryKey: keys.kadai.blockVersion(projectId ?? '', runId, n ?? 0),
    enabled: !!projectId && n !== null,
    queryFn: () =>
      unwrap<BlockVersionBody>(
        api.GET('/api/projects/{project_id}/blocks/versions/{n}', {
          params: {
            path: { project_id: projectId as string, n: n as number },
            query: { run: runId },
          },
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
export function useRollbackBlocks(projectId: string | undefined, runId = '') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (n: number) =>
      unwrap<{ version: BlockVersionHead; restored_from: number }>(
        api.POST('/api/projects/{project_id}/blocks/rollback', {
          params: { path: { project_id: projectId as string }, query: { run: runId } },
          body: { n },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.kadai.blocks(projectId ?? '', runId) })
      void qc.invalidateQueries({ queryKey: keys.kadai.blockVersions(projectId ?? '', runId) })
    },
  })
}

// ── решения работы ───────────────────────────────────────────────────────────
// Решение — запись журнала запусков (`module: "kadai"`) и каталог на томе под
// её идентификатором. Второй таблицы у службы нет: имя, номер и время описаны
// журналом, а условие, пожелания, ход стадий и блоки лежат в каталоге решения.

/**
 * Решения работы карточками, старые сверху. Пусто — их ещё не заводили.
 *
 * Список чинит и старые работы: первое решение переезжает из корня работы в
 * свой каталог со всем, что у него было (служба делает это на чтении списка),
 * поэтому спрашивать его до открытия решения обязательно.
 */
export function useKadaiRuns(projectId: string | undefined): UseQueryResult<KadaiRunCard[]> {
  return useQuery({
    queryKey: keys.kadai.runs(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<KadaiRunCard[]>(
        api.GET('/api/projects/{project_id}/kadai/runs', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

/**
 * Завести решение: запись журнала и каталог под ней.
 *
 * Ничего не считается и не стоит — прогон ставится позже, после того как
 * человек подтвердит распознанное условие. Журнал запусков работы сбрасывается
 * заодно: решение видно и в нём.
 */
export function useCreateKadaiRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, name = '' }: { projectId: string; name?: string }) =>
      unwrap<KadaiRunCard>(
        api.POST('/api/projects/{project_id}/kadai/runs', {
          params: { path: { project_id: projectId } },
          body: { name },
        }),
      ),
    onSuccess: (_карточка, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.kadai.runs(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    },
  })
}

/**
 * Снести решение: его ход стадий, условие, пожелания и блоки с историей.
 *
 * Файлы его папки контекста от него отвязываются, но с тома не уходят: файл
 * принадлежит работе, и удалять его — отдельное действие с отдельной ценой
 * ошибки. Общие файлы работы и артефакты не трогаются вовсе.
 */
export function useDeleteKadaiRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, runId }: { projectId: string; runId: string }) =>
      unwrap<void>(
        api.DELETE('/api/projects/{project_id}/kadai/runs/{run_id}', {
          params: { path: { project_id: projectId, run_id: runId } },
        }),
      ),
    onSuccess: (_ответ, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.kadai.runs(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    },
  })
}

/**
 * Папка контекста решения: только его файлы, без общих файлов работы.
 *
 * Отдельный ключ кэша, а не отбор описи работы на клиенте: описи у решений
 * разные ответы службы, и общая строка кэша показала бы файлы одного решения
 * на экране другого — ровно то, ради чего папки и заведены.
 */
export function useContextMaterials(
  projectId: string | undefined,
  runId: string,
): UseQueryResult<Material[]> {
  return useQuery({
    queryKey: keys.kadai.context(projectId ?? '', runId),
    enabled: !!projectId && !!runId,
    queryFn: () =>
      unwrap<Material[]>(
        api.GET('/api/projects/{project_id}/materials', {
          params: { path: { project_id: projectId as string }, query: { run: runId } },
        }),
      ),
    // Тот же довод, что у описи работы: список меняют загрузка и конец разбора,
    // и оба гасят ключ сами.
    staleTime: СВЕЖЕСТЬ_ПОД_ПОТОКОМ,
  })
}
