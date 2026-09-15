/**
 * api — запросы модуля «Тренажёр» одним файлом.
 *
 * Правило то же, что у соседних областей: адрес маршрута, форма ответа и ключи кэша —
 * одно знание в одном месте. Экраны зовут хуки отсюда и в клиент службы сами не ходят.
 *
 * **Набор — решение неявной работы «Тренажёр».** Служба различает наборы парой
 * «работа + набор», как доски и программы ассемблера; человеку работа не
 * показывается, но в адресах она есть.
 *
 * **Файл уезжает текстом.** Превью загрузки и замены принимают `{text, filename}`:
 * сайт читает выбранный файл сам (`File.text()`), поэтому потолок размера проверяется
 * до отправки, а вставленный текст и файл идут одним путём.
 *
 * **Адреса и тела проверяются схемой** (`schema.d.ts`), а формы ответов названы явно
 * в `types.ts`: обработчики службы объявлены словарями, и вывод из схемы дал бы
 * `Record<string, unknown>`.
 *
 * Запросы генерации и черновика живут рядом с их экранами (`generate/data.ts`).
 *
 * **Прогресс считает только служба.** После ответов захода, замены набора и сброса
 * настроек здесь сбрасываются ключи набора и библиотеки, а доли не пересчитываются.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { ApiError, api, keys, unwrap } from '@/api'
import { withBase } from '@/lib/basePath'

import type {
  AnswerBody,
  CardSet,
  CardSetInfo,
  CardSettings,
  CardsPage,
  CardsQuery,
  CreatedSet,
  PreviewResult,
  ReplaceDone,
  ReplacePreview,
  SessionPreset,
  SessionStart,
  SessionState,
} from './types'

/** Потолок файла набора — тот же, что у службы. */
export const CARDS_FILE_MAX_BYTES = 5 * 1024 * 1024

function путь(projectId: string, setId: string) {
  return { project_id: projectId, set_id: setId }
}

// ── ключи кэша ───────────────────────────────────────────────────────────────

/**
 * Ключи модуля. Всё под `'cards'`: смена пространства и выход гасят модуль одним
 * `invalidateQueries({queryKey: ['cards']})`.
 */
export const cardsKeys = {
  all: ['cards'] as const,
  setsAll: ['cards', 'sets'] as const,
  sets: (workspaceId: string) => ['cards', 'sets', workspaceId] as const,
  set: (projectId: string, setId: string) => ['cards', 'set', projectId, setId] as const,
  cardsAll: (projectId: string, setId: string) => ['cards', 'set', projectId, setId, 'cards'] as const,
  /** Под ключом набора: сброс прогресса набора перечитывает и незаконченный заход. */
  openSession: (projectId: string, setId: string) => ['cards', 'set', projectId, setId, 'open-session'] as const,
  cards: (projectId: string, setId: string, q: CardsQuery) =>
    ['cards', 'set', projectId, setId, 'cards', q.from ?? 0, q.to ?? 0, q.q ?? '', q.topic ?? ''] as const,
  session: (projectId: string, sessionId: string) => ['cards', 'session', projectId, sessionId] as const,
}

// ── библиотека ───────────────────────────────────────────────────────────────

/** Наборы пространства с моей долей «знаю». */
export function useCardSets(workspaceId: string | undefined): UseQueryResult<CardSetInfo[]> {
  return useQuery({
    queryKey: cardsKeys.sets(workspaceId ?? ''),
    enabled: !!workspaceId,
    queryFn: () =>
      unwrap<CardSetInfo[]>(api.GET('/api/cards/sets', { params: { query: { workspace_id: workspaceId ?? '' } } })),
  })
}

// ── загрузка ─────────────────────────────────────────────────────────────────

export interface CardsSource {
  text: string
  /** Имя файла: по расширению служба выбирает разбор (`.json`, `.csv`, `.tsv`); без `title` в файле — название набора. */
  filename: string
}

export function previewCards(body: CardsSource): Promise<PreviewResult> {
  return unwrap<PreviewResult>(api.POST('/api/cards/preview', { body }))
}

/** Разобрать файл в черновик и вернуть проблемы по строкам. Ничего не создаёт. */
export function usePreviewCards() {
  return useMutation({ mutationFn: previewCards })
}

export interface CreateSetBody {
  workspace_id: string
  draft_id: string
  /** Создать только из годных карточек; без флага черновик с проблемами служба не примет. */
  only_valid?: boolean
}

/** Создать набор из черновика превью. */
export function useCreateCardSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateSetBody) =>
      unwrap<CreatedSet>(api.POST('/api/cards/sets', { body: { ...body, only_valid: body.only_valid ?? false } })),
    onSuccess: (_ответ, { workspace_id }) => {
      void qc.invalidateQueries({ queryKey: cardsKeys.sets(workspace_id) })
      // Неявная работа могла завестись этим же нажатием.
      void qc.invalidateQueries({ queryKey: keys.projects.list(workspace_id, false) })
    },
  })
}

// ── набор ────────────────────────────────────────────────────────────────────

export function fetchCardSet(projectId: string, setId: string): Promise<CardSet> {
  return unwrap<CardSet>(api.GET('/api/projects/{project_id}/cards/sets/{set_id}', { params: { path: путь(projectId, setId) } }))
}

/** Набор без карточек: темы, рекомендуемые и мои настройки, мой прогресс. */
export function useCardSet(projectId: string | undefined, setId: string | undefined): UseQueryResult<CardSet> {
  return useQuery({
    queryKey: cardsKeys.set(projectId ?? '', setId ?? ''),
    enabled: !!projectId && !!setId,
    queryFn: () => fetchCardSet(projectId ?? '', setId ?? ''),
  })
}

function запросКарточек(q: CardsQuery): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  if (q.from !== undefined) out.from = q.from
  if (q.to !== undefined) out.to = q.to
  if (q.q) out.q = q.q
  if (q.topic) out.topic = q.topic
  return out
}

/** Карточки набора `[from, to)` с поиском и темой. Заход дочитывает ими карточки после первых двадцати. */
export function fetchCards(projectId: string, setId: string, q: CardsQuery = {}): Promise<CardsPage> {
  return unwrap<CardsPage>(
    api.GET('/api/projects/{project_id}/cards/sets/{set_id}/cards', {
      params: { path: путь(projectId, setId), query: запросКарточек(q) },
    }),
  )
}

/** Страница карточек; при смене поиска прежний список держится на экране, пока не придёт новый. */
export function useCards(projectId: string | undefined, setId: string | undefined, q: CardsQuery): UseQueryResult<CardsPage> {
  return useQuery({
    queryKey: cardsKeys.cards(projectId ?? '', setId ?? '', q),
    enabled: !!projectId && !!setId,
    queryFn: () => fetchCards(projectId ?? '', setId ?? '', q),
    placeholderData: keepPreviousData,
  })
}

export interface SetAddress {
  projectId: string
  setId: string
}

/** Рекомендуемые настройки набора — для всех участников (редактор). */
export function usePutDefaults() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, setId, settings }: SetAddress & { settings: CardSettings }) =>
      unwrap(api.PUT('/api/projects/{project_id}/cards/sets/{set_id}/defaults', { params: { path: путь(projectId, setId) }, body: settings })),
    onSuccess: (_ответ, { projectId, setId, settings }) => {
      qc.setQueryData<CardSet>(cardsKeys.set(projectId, setId), (было) => (было ? { ...было, defaults: settings } : было))
    },
  })
}

export function putMySettings(projectId: string, setId: string, settings: CardSettings): Promise<unknown> {
  return unwrap(
    api.PUT('/api/projects/{project_id}/cards/sets/{set_id}/my-settings', {
      params: { path: путь(projectId, setId) },
      body: { ...settings, reset: false },
    }),
  )
}

/**
 * Мои настройки захода. Кэш набора меняется сразу, до ответа службы: переключатели
 * не должны отскакивать назад, пока запрос в пути.
 */
export function usePutMySettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, setId, settings }: SetAddress & { settings: CardSettings }) => putMySettings(projectId, setId, settings),
    onMutate: ({ projectId, setId, settings }) => {
      qc.setQueryData<CardSet>(cardsKeys.set(projectId, setId), (было) => (было ? { ...было, my_settings: settings } : было))
    },
  })
}

/** Превью замены набора новым файлом: проблемы и `+новых / изменены / удалены`. */
export function useReplacePreview() {
  return useMutation({
    mutationFn: ({ projectId, setId, text, filename }: SetAddress & CardsSource) =>
      unwrap<ReplacePreview>(
        api.POST('/api/projects/{project_id}/cards/sets/{set_id}/replace/preview', {
          params: { path: путь(projectId, setId) },
          body: { text, filename },
        }),
      ),
  })
}

/** Заменить набор черновиком превью — новая версия, прогресс сохраняется по ключам карточек. */
export function useReplaceSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, setId, draftId, onlyValid }: SetAddress & { draftId: string; onlyValid?: boolean }) =>
      unwrap<ReplaceDone>(
        api.POST('/api/projects/{project_id}/cards/sets/{set_id}/replace', {
          params: { path: путь(projectId, setId) },
          body: { draft_id: draftId, only_valid: !!onlyValid },
        }),
      ),
    onSuccess: (_ответ, { projectId, setId }) => {
      void qc.invalidateQueries({ queryKey: cardsKeys.set(projectId, setId) })
      void qc.invalidateQueries({ queryKey: cardsKeys.setsAll })
    },
  })
}

/** Переименовать набор или сменить описание (редактор). */
export function useUpdateCardSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, setId, title, description }: SetAddress & { title?: string; description?: string }) =>
      unwrap(
        api.PATCH('/api/projects/{project_id}/cards/sets/{set_id}', {
          params: { path: путь(projectId, setId) },
          body: {
            ...(title !== undefined ? { title } : {}),
            ...(description !== undefined ? { description } : {}),
          },
        }),
      ),
    onSuccess: (_ответ, { projectId, setId, title, description }) => {
      qc.setQueryData<CardSet>(cardsKeys.set(projectId, setId), (было) =>
        было
          ? { ...было, ...(title !== undefined ? { title } : {}), ...(description !== undefined ? { description } : {}) }
          : было,
      )
      void qc.invalidateQueries({ queryKey: cardsKeys.setsAll })
    },
  })
}

/** Удалить набор (редактор). Попытки остаются в истории службы. */
export function useDeleteCardSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, setId }: SetAddress) =>
      unwrap<void>(api.DELETE('/api/projects/{project_id}/cards/sets/{set_id}', { params: { path: путь(projectId, setId) } })),
    onSuccess: (_ответ, { projectId, setId }) => {
      qc.removeQueries({ queryKey: cardsKeys.set(projectId, setId) })
      void qc.invalidateQueries({ queryKey: cardsKeys.setsAll })
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    },
  })
}

// ── скачать ──────────────────────────────────────────────────────────────────

/**
 * Набор файлом `.json` в каноническом виде (с id у каждой карточки). Мимо
 * сгенерированного клиента: ответ отдаётся файлом и нужен текстом как есть, без
 * разбора в объект. Отказ приходит тем же `{"error":{code}}` и превращается в тот же
 * `ApiError`.
 */
export async function fetchCardSetFile(projectId: string, setId: string): Promise<string> {
  const адрес = withBase(
    `/api/projects/${encodeURIComponent(projectId)}/cards/sets/${encodeURIComponent(setId)}/download?format=json`,
  )
  let ответ: Response
  try {
    ответ = await fetch(адрес, { credentials: 'include' })
  } catch (cause) {
    throw ApiError.network(cause)
  }
  if (!ответ.ok) {
    const тело = await ответ.json().catch(() => undefined)
    throw ApiError.from(тело, ответ.status, ответ.headers.get('X-Request-Id') ?? undefined)
  }
  return ответ.text()
}

/** Имя файла из названия набора: без символов, которые не любят файловые системы. */
export function cardsFileName(title: string, ext = 'json'): string {
  // Управляющие символы (коды до 32) — по коду, а не в классе регулярки.
  const base = Array.from(title.trim(), (ch) => (ch.charCodeAt(0) < 32 ? ' ' : ch))
    .join('')
    .replace(/[\\/:*?"<>|]+/g, ' ')
    .replace(/\s+/g, ' ')
    .slice(0, 80)
    .trim()
  return `${base || 'cards'}.${ext}`
}

/**
 * Отдать текст браузеру файлом. Черновик сохраняется так же: его JSON уже есть на
 * клиенте, и лишний запрос к службе за тем же текстом ничего бы не добавил.
 */
export function saveTextFile(name: string, text: string, type = 'application/json;charset=utf-8'): void {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Скачать набор `.json`. */
export function useDownloadCardSet() {
  return useMutation({
    mutationFn: async ({ projectId, setId, title }: SetAddress & { title: string }) => {
      const text = await fetchCardSetFile(projectId, setId)
      saveTextFile(cardsFileName(title), text)
    },
  })
}

// ── заход ────────────────────────────────────────────────────────────────────

export function startSession(projectId: string, setId: string, preset: SessionPreset = 'settings'): Promise<SessionStart> {
  return unwrap<SessionStart>(
    api.POST('/api/projects/{project_id}/cards/sets/{set_id}/sessions', {
      params: { path: путь(projectId, setId) },
      body: { preset },
    }),
  )
}

/** Завести заход: служба раскладывает порядок по настройкам и отдаёт первые карточки. */
export function useStartSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, setId, preset }: SetAddress & { preset?: SessionPreset }) => startSession(projectId, setId, preset),
    // Новый заход закрывает прежний незаконченный.
    onSuccess: (_ответ, { projectId, setId }) => void qc.invalidateQueries({ queryKey: cardsKeys.openSession(projectId, setId) }),
  })
}

/**
 * Мой незаконченный заход набора с любого устройства: текущая версия, моложе 12 часов.
 * `null` — продолжать нечего (служба отвечает 204).
 */
export async function fetchOpenSession(projectId: string, setId: string): Promise<SessionState | null> {
  const заход = await unwrap<SessionState | undefined>(
    api.GET('/api/projects/{project_id}/cards/sets/{set_id}/sessions/open', { params: { path: путь(projectId, setId) } }),
  )
  return заход?.session_id ? заход : null
}

/** «Продолжить» на странице набора и на экране захода без id в адресе. */
export function useOpenSession(projectId: string | undefined, setId: string | undefined): UseQueryResult<SessionState | null> {
  return useQuery({
    queryKey: cardsKeys.openSession(projectId ?? '', setId ?? ''),
    enabled: !!projectId && !!setId,
    queryFn: () => fetchOpenSession(projectId ?? '', setId ?? ''),
  })
}

export function fetchSession(projectId: string, sessionId: string): Promise<SessionState> {
  return unwrap<SessionState>(
    api.GET('/api/projects/{project_id}/cards/sessions/{session_id}', {
      params: { path: { project_id: projectId, session_id: sessionId } },
    }),
  )
}

/** Заход с тома: порядок ключей, позиция, записанные ответы. */
export function useSession(projectId: string | undefined, sessionId: string | undefined): UseQueryResult<SessionState> {
  return useQuery({
    queryKey: cardsKeys.session(projectId ?? '', sessionId ?? ''),
    enabled: !!projectId && !!sessionId,
    queryFn: () => fetchSession(projectId ?? '', sessionId ?? ''),
    refetchOnWindowFocus: false,
  })
}

/**
 * Записать ответ захода. `client_seq` уникален в заходе, поэтому повтор того же
 * ответа из очереди вкладки служба примет один раз.
 */
export function postAnswer(projectId: string, sessionId: string, body: AnswerBody): Promise<unknown> {
  return unwrap(
    api.POST('/api/projects/{project_id}/cards/sessions/{session_id}/answers', {
      params: { path: { project_id: projectId, session_id: sessionId } },
      body,
    }),
  )
}

/** Сбросить кэш набора и библиотеки: доли «знаю» поменялись у службы. */
export function useInvalidateProgress() {
  const qc = useQueryClient()
  return (projectId: string, setId: string) => {
    void qc.invalidateQueries({ queryKey: cardsKeys.set(projectId, setId) })
    void qc.invalidateQueries({ queryKey: cardsKeys.setsAll })
  }
}
