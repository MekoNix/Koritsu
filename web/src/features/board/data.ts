/**
 * data — запросы области «Доска» одним файлом.
 *
 * То же правило, что у соседних областей: адрес маршрута, форма ответа и список
 * ключей, которые сбрасываются после изменения, — одно знание и живёт в одном
 * месте. Экраны зовут хуки, а не клиент службы.
 *
 * **Почти каждый хук берёт `boardId`.** Досок в работе несколько, у каждой своя
 * сцена, свой чистовик и своё условие; служба различает их параметром `run`, и
 * хук, который его не передаёт, показал бы на экране одной доски ответ,
 * полученный для другой.
 *
 * Доска — решение работы модуля `board`, и служба различает доски тем же
 * параметром `run`, что и решения: одна доска — один каталог на томе, одна
 * сцена, один чистовик, одно условие.
 *
 * **Список досок при этом спрашивается по пространству, а не по работе**
 * (`useWorkspaceBoards`): человек открывает раздел «Доска» и видит свои доски
 * списком, не выбирая работы. Работа никуда не делась — она осталась носителем
 * и адресом, — но выбирать её незачем, и ни один экран её не показывает.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'

import type { RecognizeIn, RecognizeOut, RecognizedCache, SceneLine } from './recognizer'
import { stepsBody } from './recognizer'
import type {
  BoardCard,
  ChatBody,
  ExcalidrawScene,
  InkSession,
  SceneBody,
  StepsBody,
  TaskBody,
  WorkspaceBoardCard,
} from './types'

/**
 * Распознать строки пачкой.
 *
 * Не хук: зовёт её не экран, а перо на паузе (`ink.ts`), и держать этот вызов в
 * состоянии React значило бы перерисовывать доску на каждый ответ. Ключи
 * MyScript наружу не уходят — за сервисом ходит служба.
 */
export function recognizeLines(body: RecognizeIn): Promise<RecognizeOut> {
  return unwrap<RecognizeOut>(api.POST('/api/board/recognize', { body }))
}

/**
 * Готовность распознавания: есть ли ключи MyScript и куда идти сокету.
 *
 * Спрашивается один раз на доску и живёт долго: ключи заводят в настройках, и
 * ответ меняется не чаще, чем туда ходят. Сессия распознавания при этом не
 * открывается — открытие стоит у MyScript одного запроса, и делает его первый
 * росчерк, а не загрузка страницы.
 */
export function useInkSession(): UseQueryResult<InkSession> {
  return useQuery({
    queryKey: keys.board.session,
    queryFn: () => unwrap<InkSession>(api.GET('/api/board/session')),
    staleTime: 10 * 60_000,
    // Отказ маршрута не должен гасить доску: без распознавания она рисует и
    // сохраняется, а полоса состояния скажет, что распознавание выключено.
    retry: false,
  })
}

/**
 * Доски текущего пространства одной лентой, новые сверху.
 *
 * Список, из которого сделан экран «Доска»: человек открывает раздел и видит
 * свои доски, не выбирая работы. Одним запросом, а не списком работ плюс
 * запросом на каждую: время такого ответа росло бы вместе с числом работ.
 */
export function useWorkspaceBoards(
  workspaceId: string | undefined,
): UseQueryResult<WorkspaceBoardCard[]> {
  return useQuery({
    queryKey: keys.board.workspace(workspaceId ?? ''),
    enabled: !!workspaceId,
    queryFn: () =>
      unwrap<WorkspaceBoardCard[]>(
        api.GET('/api/board/boards', {
          params: { query: { workspace_id: workspaceId as string } },
        }),
      ),
  })
}

/**
 * Завести доску, не называя работы: работу находит служба.
 *
 * Ответ несёт `project_id` — адрес экрана доски по-прежнему `/board/:projectId/
 * :boardId`, потому что носитель не изменился: доска это решение работы. Видеть
 * работу человеку при этом незачем, и ни один экран её не показывает.
 */
export function useCreateWorkspaceBoard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ workspaceId, name = '' }: { workspaceId: string; name?: string }) =>
      unwrap<WorkspaceBoardCard>(
        api.POST('/api/board/boards', { body: { workspace_id: workspaceId, name } }),
      ),
    onSuccess: (карточка, { workspaceId }) => {
      void qc.invalidateQueries({ queryKey: keys.board.workspace(workspaceId) })
      void qc.invalidateQueries({ queryKey: keys.board.boards(карточка.project_id) })
      // Неявная работа могла завестись этим же нажатием: список работ о ней
      // ещё не знает.
      void qc.invalidateQueries({ queryKey: keys.projects.list(workspaceId, false) })
    },
  })
}

/** Доски работы, старые сверху. Читает их экран доски — ради имени и номера. */
export function useBoards(projectId: string | undefined): UseQueryResult<BoardCard[]> {
  return useQuery({
    queryKey: keys.board.boards(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<BoardCard[]>(
        api.GET('/api/projects/{project_id}/board/boards', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

/**
 * Снести доску: её сцену, чистовик, условие и папку файлов.
 *
 * Уходит и переписка с репетитором — она живёт прогонами этой доски. Общие
 * файлы работы не трогаются: файл принадлежит работе, и удалять его — отдельное
 * действие с отдельной ценой ошибки.
 */
export function useDeleteBoard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, boardId }: { projectId: string; boardId: string }) =>
      unwrap<void>(
        api.DELETE('/api/projects/{project_id}/board/boards/{run_id}', {
          params: { path: { project_id: projectId, run_id: boardId } },
        }),
      ),
    onSuccess: (_ответ, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.board.boards(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
      // Лента пространства собрана по всем работам сразу, и какого из них
      // касается снос — здесь неизвестно: гасим её целиком.
      void qc.invalidateQueries({ queryKey: keys.board.workspaceAll })
    },
  })
}

/**
 * Сцена доски с тома.
 *
 * Читается один раз при открытии и дальше живёт в редакторе: холст — это поток
 * правок по десятку в секунду, и перечитывать его запросом означало бы стирать
 * то, что человек рисует прямо сейчас. Поэтому свежесть бесконечная, а
 * перечитывание — только явное (после 409, когда сцену изменила вторая вкладка).
 */
export function useBoardScene(
  projectId: string | undefined,
  boardId: string,
): UseQueryResult<SceneBody> {
  return useQuery({
    queryKey: keys.board.scene(projectId ?? '', boardId),
    enabled: !!projectId && !!boardId,
    queryFn: () =>
      unwrap<SceneBody>(
        api.GET('/api/projects/{project_id}/board/scene', {
          params: { path: { project_id: projectId as string }, query: { run: boardId } },
        }),
      ),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}

/**
 * Записать сцену.
 *
 * `version` — счётчик оптимистической блокировки: чужой даёт 409 и текущую
 * сцену в теле отказа. Две вкладки одной доски теряют правку **шумно**, а не
 * молча, и это единственный способ не подарить человеку пропавшее решение.
 *
 * Ответ кладётся в кэш напрямую: перечитывать сцену после записи нельзя — на
 * холсте к этой секунде уже нарисовано больше, чем уехало.
 */
export function useSaveScene() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      boardId,
      scene,
      version,
      recognized,
    }: {
      projectId: string
      boardId: string
      scene: ExcalidrawScene
      version: number
      /** Распознанное по строкам: едет со сценой, чтобы пережить перезагрузку. */
      recognized?: RecognizedCache
    }) =>
      unwrap<SceneBody>(
        api.PUT('/api/projects/{project_id}/board/scene', {
          params: { path: { project_id: projectId }, query: { run: boardId } },
          body: { scene, version, recognized },
        }),
      ),
    onSuccess: (ответ, { projectId, boardId }) => {
      qc.setQueryData<SceneBody>(keys.board.scene(projectId, boardId), ответ)
    },
  })
}

/**
 * Записать строки решения и переписать файл рядом с доской.
 *
 * Файл перезаписывается, а не версионируется: материал адресуется содержимым, и
 * «история» здесь означала бы новую строку в описи работы на каждую поправленную
 * формулу, — а опись целиком уезжает в промпт карточками и оплачивается
 * человеком. Правда о доске — сцена вместе со словарём прочитанного, который
 * едет с ней рядом; строки пересобираются из них в любой момент.
 */
export function useRebuildSteps() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      boardId,
      lines,
      recognized,
    }: {
      projectId: string
      boardId: string
      /** Строки сцены сверху вниз — в том порядке, в каком их читает человек. */
      lines: readonly SceneLine[]
      recognized: RecognizedCache
    }) =>
      unwrap<StepsBody>(
        api.PUT('/api/projects/{project_id}/board/steps', {
          params: { path: { project_id: projectId }, query: { run: boardId } },
          // Строки уезжают **готовыми**: распознаёт их сайт, и собрать их заново
          // из сцены служба не может — разбора рукописи у неё нет. Её дело —
          // сохранить их и переписать `<доска>.latex.md`.
          body: stepsBody(lines, recognized),
        }),
      ),
    onSuccess: (_ответ, { projectId, boardId }) => {
      void qc.invalidateQueries({ queryKey: keys.board.steps(projectId, boardId) })
      // Счётчик строк стоит на карточке доски в списке, а файл — в описи работы.
      void qc.invalidateQueries({ queryKey: keys.board.boards(projectId) })
      void qc.invalidateQueries({ queryKey: keys.board.workspaceAll })
      void qc.invalidateQueries({ queryKey: keys.projects.materials(projectId) })
    },
  })
}

/** Переписка с репетитором по этой доске, старые сообщения первыми. */
export function useBoardChat(
  projectId: string | undefined,
  boardId: string,
): UseQueryResult<ChatBody> {
  return useQuery({
    queryKey: keys.board.chat(projectId ?? '', boardId),
    enabled: !!projectId && !!boardId,
    queryFn: () =>
      unwrap<ChatBody>(
        api.GET('/api/projects/{project_id}/board/chat', {
          params: { path: { project_id: projectId as string }, query: { run: boardId } },
        }),
      ),
  })
}

/** Условие задачи текстом. Пусто — условие не названо, и это законное состояние. */
export function useBoardTask(
  projectId: string | undefined,
  boardId: string,
): UseQueryResult<TaskBody> {
  return useQuery({
    queryKey: keys.board.task(projectId ?? '', boardId),
    enabled: !!projectId && !!boardId,
    queryFn: () =>
      unwrap<TaskBody>(
        api.GET('/api/projects/{project_id}/board/task', {
          params: { path: { project_id: projectId as string }, query: { run: boardId } },
        }),
      ),
  })
}

/**
 * Назвать условие задачи.
 *
 * Текстом, а не материалом: условие едет модели отдельным недоверенным куском —
 * его набирает тот же человек, что рисует доску. Файл условия — обычный материал
 * папки доски, и это другая дорога.
 */
export function useSetBoardTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      boardId,
      text,
    }: {
      projectId: string
      boardId: string
      text: string
    }) =>
      unwrap<TaskBody>(
        api.PUT('/api/projects/{project_id}/board/task', {
          params: { path: { project_id: projectId }, query: { run: boardId } },
          body: { text },
        }),
      ),
    onSuccess: (ответ, { projectId, boardId }) => {
      qc.setQueryData<TaskBody>(keys.board.task(projectId, boardId), ответ)
      // Условие стоит строкой на карточке доски в списке: пока его не назвали,
      // карточка молчит о том, какую задачу на ней решают.
      void qc.invalidateQueries({ queryKey: keys.board.boards(projectId) })
    },
  })
}
