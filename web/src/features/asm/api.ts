/**
 * api — запросы модуля «Ассемблер» одним файлом.
 *
 * То же правило, что у соседних областей: адрес маршрута, форма ответа и ключи
 * кэша — одно знание в одном месте. Окна зовут хуки отсюда или берут данные из
 * `useAsm()`, а не ходят в клиент службы сами.
 *
 * **Программа — решение работы.** Служба различает программы парой «работа +
 * решение», как доски; человеку работа не показывается, но в адресах она есть.
 * Окнам пару передавать незачем: её держит `AsmAddressContext`, который ставит
 * страница программы, и хуки вроде `useAsmDebugx` берут адрес оттуда.
 *
 * **Адреса и тела проверяются схемой** (`schema.d.ts`), а формы ответов названы
 * здесь явно, как у доски: схема описывает регистры и шаги словарями строк, а
 * окнам нужны имена полей.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { createContext, useContext } from 'react'

import { ApiError, api, isTerminal, keys, unwrap } from '@/api'
import type { Job } from '@/api/hooks'

import type { AsmAnchor, AsmRunSummary, AsmSettings, AsmStep } from './types'

function путь(projectId: string, programId: string) {
  return { project_id: projectId, program_id: programId }
}

// ── формы ────────────────────────────────────────────────────────────────────

/** `GET /api/asm/status`: что нашлось из инструментов на машине службы. */
export interface AsmStatus {
  available: boolean
  dosbox: boolean
  tasm: boolean
  tlink: boolean
  debugx: boolean
}

/** Карточка программы в списке пространства. */
export interface AsmProgramCard {
  project_id: string
  program_id: string
  name: string
  n: number
  updated_at: string | null
  last_status: AsmRunSummary['status'] | null
}

/** Программа целиком: исходник, версия записи и настройки прогона. */
export interface AsmProgram {
  project_id: string
  program_id: string
  name: string
  n: number
  source: string
  version: number
  settings: Partial<AsmSettings>
  breakpoints: number[]
  watches: string[]
  last_run_no: number | null
}

export interface AsmStepsPage {
  from: number
  to: number
  total: number
  steps: AsmStep[]
}

export interface AsmChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  anchor: AsmAnchor | null
  step: number | null
  run_no: number | null
  created_at: string
}

/** Вопрос агенту. `endpoint` — пресет модели, который платит за ответ. */
export interface AsmChatSend {
  text: string
  anchor: AsmAnchor | null
  step: number | null
  run_no: number | null
  endpoint: string
}

export type AsmDump = AsmRunSummary['dumps'][number]

/** Настройки по умолчанию — те же, что у `RunRequest` ядра. */
export const DEFAULT_SETTINGS: AsmSettings = {
  stdin: '',
  step_limit: 100_000,
  mode32: false,
  tasm_flags: ['/zi', '/l'],
  tlink_flags: ['/v'],
  breakpoints: [],
  watches: [],
}

/** Потолок лимита шагов; выше служба не примет. */
export const STEP_LIMIT_MAX = 500_000

/** Код отказа при записи исходника поверх чужой версии. */
export const SOURCE_CONFLICT = 'source_conflict'

/** Настройки из ответа службы: пропущенное поле — значение по умолчанию. */
export function settingsOf(p: AsmProgram): AsmSettings {
  const s = p.settings ?? {}
  return {
    stdin: s.stdin ?? DEFAULT_SETTINGS.stdin,
    step_limit: s.step_limit ?? DEFAULT_SETTINGS.step_limit,
    mode32: s.mode32 ?? DEFAULT_SETTINGS.mode32,
    tasm_flags: s.tasm_flags ?? DEFAULT_SETTINGS.tasm_flags,
    tlink_flags: s.tlink_flags ?? DEFAULT_SETTINGS.tlink_flags,
    breakpoints: p.breakpoints ?? s.breakpoints ?? [],
    watches: p.watches ?? s.watches ?? [],
  }
}

// ── ключи кэша ───────────────────────────────────────────────────────────────

/** Ключи модуля живут в общем `keys` (`api/queryKeys.ts`); здесь — короткое имя. */
export const asmKeys = keys.asm

// ── адрес открытой программы ─────────────────────────────────────────────────

export interface AsmAddress {
  projectId: string
  programId: string
}

/** Ставит страница программы; окна берут адрес отсюда. */
export const AsmAddressContext = createContext<AsmAddress | null>(null)

export function useAsmAddress(): AsmAddress {
  const адрес = useContext(AsmAddressContext)
  if (!адрес) throw new Error('useAsmAddress вызван вне страницы программы')
  return адрес
}

// ── список и программа ───────────────────────────────────────────────────────

/** Готовы ли инструменты. Меняется только выкатом, поэтому живёт долго. */
export function useAsmStatus(): UseQueryResult<AsmStatus> {
  return useQuery({
    queryKey: asmKeys.status,
    queryFn: () => unwrap<AsmStatus>(api.GET('/api/asm/status')),
    staleTime: 10 * 60_000,
    retry: false,
  })
}

/** Программы текущего пространства одной лентой. */
export function useAsmPrograms(workspaceId: string | undefined): UseQueryResult<AsmProgramCard[]> {
  return useQuery({
    queryKey: asmKeys.programs(workspaceId ?? ''),
    enabled: !!workspaceId,
    queryFn: () =>
      unwrap<AsmProgramCard[]>(
        api.GET('/api/asm/programs', { params: { query: { workspace_id: workspaceId ?? '' } } }),
      ),
  })
}

/** Завести программу, не называя работы: неявную работу находит служба. */
export function useCreateAsmProgram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ workspaceId, name }: { workspaceId: string; name?: string }) =>
      unwrap<{ project_id: string; program_id: string; name: string; n: number }>(
        api.POST('/api/asm/programs', { body: { workspace_id: workspaceId, name: name ?? '' } }),
      ),
    onSuccess: (_ответ, { workspaceId }) => {
      void qc.invalidateQueries({ queryKey: asmKeys.programs(workspaceId) })
      // Неявная работа могла завестись этим же нажатием.
      void qc.invalidateQueries({ queryKey: keys.projects.list(workspaceId, false) })
    },
  })
}

/**
 * Записи исходника, которые ещё не кончились, по программам. Страница, которую
 * закрыли с незаписанной правкой, дописывает её уже после ухода; открытая снова
 * сразу, она прочитала бы том раньше этой записи — текст без правки и старую
 * версию, на которой первая же правка получит 409. Поэтому чтение программы
 * ждёт, пока запись кончится.
 */
const незаконченныеЗаписи = new Map<string, Promise<unknown>>()

/** Придержать чтение программы, пока `запись` не кончится — удачей или отказом. */
export function holdAsmProgramRead(programId: string, запись: Promise<unknown>): void {
  const все = Promise.allSettled([незаконченныеЗаписи.get(programId), запись])
  незаконченныеЗаписи.set(programId, все)
  void все.then(() => {
    if (незаконченныеЗаписи.get(programId) === все) незаконченныеЗаписи.delete(programId)
  })
}

/** `waitWrites: false` — для чтения изнутри самой записи (после 409), иначе оно ждало бы себя. */
export async function fetchAsmProgram(
  projectId: string,
  programId: string,
  { waitWrites = true }: { waitWrites?: boolean } = {},
): Promise<AsmProgram> {
  if (waitWrites) await незаконченныеЗаписи.get(programId)
  return unwrap<AsmProgram>(
    api.GET('/api/projects/{project_id}/asm/programs/{program_id}', {
      params: { path: путь(projectId, programId) },
    }),
  )
}

/**
 * Программа с тома. Дальше она живёт в редакторе: исходник правится быстрее,
 * чем уезжает, и перечитывание стирало бы набранное. Поэтому свежесть
 * бесконечная и само по себе чтение не повторяется.
 *
 * Страница программы берёт `fresh`: открывая программу, она читает её с тома
 * заново, даже если в кэше лежит прошлое открытие. Кэш не знает ни версий,
 * записанных с тех пор, ни новых прогонов: редактор, начавший со старого
 * текста и старой версии, получил бы 409 на первой же правке, а экран показал
 * бы давнюю сборку с её ошибками.
 */
export function useAsmProgram(
  projectId: string,
  programId: string,
  opts: { fresh?: boolean } = {},
): UseQueryResult<AsmProgram> {
  return useQuery({
    queryKey: asmKeys.program(projectId, programId),
    enabled: !!projectId && !!programId,
    queryFn: () => fetchAsmProgram(projectId, programId),
    staleTime: Infinity,
    refetchOnMount: opts.fresh ? 'always' : true,
    refetchOnWindowFocus: false,
  })
}

/**
 * Записать исходник. `version` — счётчик оптимистической блокировки: чужая
 * версия даёт `409 source_conflict`, и две вкладки теряют правку шумно, а не
 * молча. `keepalive` — запись со страницы, которая закрывается: обычный запрос
 * браузер оборвал бы вместе с ней.
 */
export function putAsmSource(
  projectId: string,
  programId: string,
  source: string,
  version: number,
  { keepalive = false }: { keepalive?: boolean } = {},
): Promise<{ version: number }> {
  return unwrap<{ version: number }>(
    api.PUT('/api/projects/{project_id}/asm/programs/{program_id}/source', {
      params: { path: путь(projectId, programId) },
      body: { source, version },
      ...(keepalive ? { keepalive: true } : {}),
    }),
  )
}

export function putAsmSettings(projectId: string, programId: string, settings: AsmSettings): Promise<unknown> {
  return unwrap(
    api.PUT('/api/projects/{project_id}/asm/programs/{program_id}/settings', {
      params: { path: путь(projectId, programId) },
      body: settings,
    }),
  )
}

export function useRenameAsmProgram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, programId, name }: AsmAddress & { name: string }) =>
      unwrap(
        api.PATCH('/api/projects/{project_id}/asm/programs/{program_id}', {
          params: { path: путь(projectId, programId) },
          body: { name },
        }),
      ),
    onSuccess: (_ответ, { projectId, programId, name }) => {
      qc.setQueryData<AsmProgram>(asmKeys.program(projectId, programId), (было) =>
        было ? { ...было, name } : было,
      )
      void qc.invalidateQueries({ queryKey: asmKeys.programsAll })
    },
  })
}

export function useDeleteAsmProgram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, programId }: AsmAddress) =>
      unwrap<void>(
        api.DELETE('/api/projects/{project_id}/asm/programs/{program_id}', {
          params: { path: путь(projectId, programId) },
        }),
      ),
    onSuccess: (_ответ, { projectId }) => {
      void qc.invalidateQueries({ queryKey: asmKeys.programsAll })
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    },
  })
}

// ── прогоны ──────────────────────────────────────────────────────────────────

/** Поставить сборку или прогон. Служба берёт исходник и настройки на момент постановки. */
export function startAsmRun(
  projectId: string,
  programId: string,
  mode: 'build' | 'run',
): Promise<{ job_id: string; run_no: number }> {
  return unwrap<{ job_id: string; run_no: number }>(
    api.POST('/api/projects/{project_id}/asm/programs/{program_id}/runs', {
      params: { path: путь(projectId, programId) },
      body: { mode },
    }),
  )
}

export function fetchAsmRun(projectId: string, programId: string, runNo: number): Promise<AsmRunSummary> {
  return unwrap<AsmRunSummary>(
    api.GET('/api/projects/{project_id}/asm/programs/{program_id}/runs/{run_no}', {
      params: { path: { ...путь(projectId, programId), run_no: runNo } },
    }),
  )
}

/** Сводка прогона без шагов. Идущий прогон перечитывает страница по событиям задания. */
export function useAsmRun(
  projectId: string,
  programId: string,
  runNo: number | null | undefined,
): UseQueryResult<AsmRunSummary> {
  return useQuery({
    queryKey: asmKeys.run(projectId, programId, runNo ?? 0),
    enabled: !!projectId && !!programId && !!runNo,
    queryFn: () => fetchAsmRun(projectId, programId, runNo as number),
    refetchOnWindowFocus: false,
  })
}

/** Страница шагов; `to − from` не больше 2000. */
export function fetchAsmSteps(
  projectId: string,
  programId: string,
  runNo: number,
  from: number,
  to: number,
): Promise<AsmStepsPage> {
  return unwrap<AsmStepsPage>(
    api.GET('/api/projects/{project_id}/asm/programs/{program_id}/runs/{run_no}/steps', {
      params: { path: { ...путь(projectId, programId), run_no: runNo }, query: { from, to } },
    }),
  )
}

/**
 * Сырой вывод DebugX кусок за куском по номерам шагов. Законченный прогон не
 * меняется, поэтому кусок, раз прочитанный, не перечитывается.
 */
export function useAsmDebugx(
  runNo: number | undefined,
  from: number,
  to: number,
): UseQueryResult<{ text: string }> {
  const { projectId, programId } = useAsmAddress()
  return useQuery({
    queryKey: asmKeys.debugx(projectId, programId, runNo ?? 0, from, to),
    enabled: !!runNo && to >= from,
    queryFn: () =>
      unwrap<{ text: string }>(
        api.GET('/api/projects/{project_id}/asm/programs/{program_id}/runs/{run_no}/debugx', {
          params: { path: { ...путь(projectId, programId), run_no: runNo as number }, query: { from, to } },
        }),
      ),
    staleTime: Infinity,
  })
}

function fetchJob(id: string): Promise<Job> {
  return unwrap<Job>(api.GET('/api/jobs/{job_id}', { params: { path: { job_id: id } } }))
}

const пауза = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * Дождаться конца задания опросом. Для коротких заданий (`asm_memory` — один
 * перезапуск до шага), где поток событий открывать дороже, чем спросить
 * карточку несколько раз.
 */
export async function waitJob(id: string, timeoutMs = 60_000): Promise<Job> {
  const до = Date.now() + timeoutMs
  let шаг = 300
  for (;;) {
    const задание = await fetchJob(id)
    if (isTerminal(задание.status)) return задание
    if (Date.now() > до) throw new ApiError('timeout', 'asm_memory')
    await пауза(шаг)
    шаг = Math.min(шаг * 1.5, 2000)
  }
}

/** Дампы памяти на шаге, которых нет в трассе: служба перезапускает программу до шага. */
export async function requestAsmMemory(
  projectId: string,
  programId: string,
  runNo: number,
  step: number,
  ranges: { seg: string; off: string; len: number }[],
): Promise<AsmDump[]> {
  const { job_id } = await unwrap<{ job_id: string }>(
    api.POST('/api/projects/{project_id}/asm/programs/{program_id}/runs/{run_no}/memory', {
      params: { path: { ...путь(projectId, programId), run_no: runNo } },
      body: { step, ranges },
    }),
  )
  const задание = await waitJob(job_id)
  if (задание.status !== 'done') {
    const беда = (задание.error ?? {}) as { code?: string; message?: string }
    throw new ApiError(беда.code || 'unknown', беда.message || '')
  }
  return (задание.result as { dumps?: AsmDump[] } | null)?.dumps ?? []
}

// ── переписка с агентом ──────────────────────────────────────────────────────

/** Переписка с агентом по открытой программе, старые сообщения первыми. */
export function useAsmChat(): UseQueryResult<{ messages: AsmChatMessage[] }> {
  const { projectId, programId } = useAsmAddress()
  return useQuery({
    queryKey: asmKeys.chat(projectId, programId),
    enabled: !!projectId && !!programId,
    queryFn: () =>
      unwrap<{ messages: AsmChatMessage[] }>(
        api.GET('/api/projects/{project_id}/asm/programs/{program_id}/chat', {
          params: { path: путь(projectId, programId) },
        }),
      ),
  })
}

/**
 * Отправить вопрос агенту; ответ приходит заданием `asm_chat`, а в переписку
 * вопрос и ответ попадают вместе, когда задание кончилось. Поэтому ленту здесь
 * не сбрасываем: её перечитывает окно по концу задания.
 */
export function usePostAsmChat() {
  const { projectId, programId } = useAsmAddress()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AsmChatSend) =>
      unwrap<{ job_id: string }>(
        api.POST('/api/projects/{project_id}/asm/programs/{program_id}/chat', {
          params: { path: путь(projectId, programId) },
          body,
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.jobs.all })
    },
  })
}
