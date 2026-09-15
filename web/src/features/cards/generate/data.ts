/**
 * data — запросы генерации и черновика набора.
 *
 * Черновик живёт на сервере (каталог черновиков пользователя на томе), а не в
 * браузере: перезагрузка страницы, второе устройство и закрытая вкладка
 * открывают тот же черновик по адресу `/cards/drafts/:draftId`.
 *
 * Файлы для генерации лежат в неявной работе «Тренажёр» пространства — там же,
 * где наборы. Работу человек не выбирает: у модуля нет работ в интерфейсе, и
 * загрузка идёт по пространству (`/api/cards/materials?workspace_id=`).
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, unwrap } from '@/api'

import type {
  CreatedSet,
  Draft,
  DraftSaveBody,
  DraftUpdated,
  GenerateBody as BaseGenerateBody,
  GenerateLength,
  GenerateStarted,
} from '../types'

/** Ключи кэша генерации и черновика. Корень `cards` общий у модуля. */
export const generateKeys = {
  draft: (id: string) => ['cards', 'drafts', id] as const,
  materials: (workspaceId: string) => ['cards', 'materials', workspaceId] as const,
}

/** Длина ответа: кратко или развёрнуто с разбором. */
export type AnswerLength = GenerateLength

/** Тело `POST /api/cards/generate` с полями догенерации. */
export type GenerateBody = BaseGenerateBody & {
  /** Догенерация: дописать в этот черновик… */
  draft_id?: string
  /** …карточки по этой теме (название). */
  topic?: string
}

/** Файл, загруженный для генерации (`GET /api/cards/materials`). */
export type CardsMaterial = {
  material_id: string
  name: string
  kind: string
  /** `ready` — разобран, можно отдавать агенту; `pending` — разбирается; `failed` — разбор упал. */
  status: 'ready' | 'pending' | 'failed'
  /** Почему разбор упал — у `failed`. */
  error?: string | null
}

/** Разбор файла закончился удачно. */
export function materialReady(m: CardsMaterial): boolean {
  return m.status === 'ready'
}

/** Разбор файла не удался — отдавать его агенту бессмысленно. */
export function materialFailed(m: CardsMaterial): boolean {
  return m.status === 'failed'
}

// ── генерация ────────────────────────────────────────────────────────────────

export function useGenerate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: GenerateBody) =>
      unwrap<GenerateStarted>(api.POST('/api/cards/generate', { body })),
    onSuccess: (answer) => {
      void qc.invalidateQueries({ queryKey: ['jobs'] })
      void qc.invalidateQueries({ queryKey: generateKeys.draft(answer.draft_id) })
    },
  })
}

// ── файлы ────────────────────────────────────────────────────────────────────

/**
 * Файлы пространства для генерации. Пока хоть один разбирается, список
 * перечитывается сам: иначе галочка у свежего файла не стала бы доступной до
 * перезагрузки страницы.
 */
export function useCardsMaterials(workspaceId: string | undefined): UseQueryResult<CardsMaterial[]> {
  return useQuery({
    queryKey: generateKeys.materials(workspaceId ?? ''),
    enabled: !!workspaceId,
    queryFn: () =>
      unwrap<CardsMaterial[]>(
        api.GET('/api/cards/materials', {
          params: { query: { workspace_id: workspaceId as string } },
        }),
      ),
    refetchInterval: (query) => {
      const list = query.state.data as CardsMaterial[] | undefined
      return list?.some((m) => !materialReady(m) && !materialFailed(m)) ? 2000 : false
    },
  })
}

/** Загрузить один файл в материалы «Тренажёра» пространства. */
export function useUploadCardsMaterial() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ workspaceId, file }: { workspaceId: string; file: File }) => {
      const form = new FormData()
      form.append('file', file, file.name)
      return unwrap<CardsMaterial>(
        api.POST('/api/cards/materials', {
          params: { query: { workspace_id: workspaceId } },
          body: { file: '' },
          bodySerializer: () => form,
        }),
      )
    },
    onSuccess: (_m, { workspaceId }) => {
      void qc.invalidateQueries({ queryKey: generateKeys.materials(workspaceId) })
    },
  })
}

// ── черновик ─────────────────────────────────────────────────────────────────

export function useDraft(draftId: string | undefined): UseQueryResult<Draft> {
  return useQuery({
    queryKey: generateKeys.draft(draftId ?? ''),
    enabled: !!draftId,
    queryFn: () =>
      unwrap<Draft>(
        api.GET('/api/cards/drafts/{draft_id}', {
          params: { path: { draft_id: draftId as string } },
        }),
      ),
    // Черновика нет (истёк срок, чужой) — повторять незачем.
    retry: false,
  })
}

/**
 * Сохранить черновик целой JSON-строкой набора. Служба разбирает её тем же
 * разбором, что загрузку файла, и отвечает проблемами — их и показывает экран.
 */
export function useSaveDraftText(draftId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text: string) =>
      unwrap<DraftUpdated>(
        api.PUT('/api/cards/drafts/{draft_id}', {
          params: { path: { draft_id: draftId as string } },
          body: { text },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: generateKeys.draft(draftId ?? '') })
    },
  })
}

/** Черновик → набор (новый или новой версией существующего). */
export function useSaveDraftAsSet(draftId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (target: DraftSaveBody) =>
      unwrap<CreatedSet>(
        api.POST('/api/cards/drafts/{draft_id}/save', {
          params: { path: { draft_id: draftId as string } },
          // Экран черновика помечает отклонённые карточки «в набор не попадёт»
          // до сохранения, поэтому сохраняются только годные — явно.
          body: { ...target, only_valid: true },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['cards'] })
    },
  })
}
