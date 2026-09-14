/* eslint-disable react-refresh/only-export-components --
 * Контекст, провайдер и хуки держатся в одном файле намеренно: они бесполезны
 * друг без друга, как и крошки оболочки.
 */
/**
 * store — состояние открытой программы: исходник, настройки, прогон, трасса.
 *
 * Окна берут всё из `useAsm()` и больше ни из чего: док не знает, что внутри
 * окна, окно не знает, в какой оно группе. Каркасу (меню, клавиши, док) нужно
 * ещё немного своего — это `useAsmUi()`, окнам он не нужен.
 *
 * **Трасса ходится в браузере.** Прогон присылает сводку, а шаги лежат на
 * службе страницами; шаг, которого ещё нет, `getStep` возвращает пустым и сам
 * просит страницу — окно перерисуется, когда она приедет. Поиск вперёд («до
 * курсора», «до точки», «шаг с обходом CALL») догружает страницы по очереди,
 * пока не найдёт: трасса на сто тысяч шагов — это полсотни запросов, а не один
 * ответ на сорок мегабайт.
 *
 * **Шаг `k` — состояние после `k`-й команды**, строка «сейчас» — `step.next?.line`.
 * Поэтому «до строки N» — первый шаг, у которого следующей стоит строка N, и это
 * одинаково работает на последнем шаге и на границе свёрнутой середины трассы.
 *
 * **Исходник уезжает с паузой и с версией.** На том пишется только правка,
 * сделанная в этой вкладке: текст, с которым страница открылась, там уже
 * лежит, и отправить его обратно значило бы разве что затереть чужое. Правка
 * уезжает через секунду тишины; чужая версия даёт 409, и запись
 * останавливается. Если на томе ровно наш текст или своей незаписанной правки
 * уже нет, страница молча берёт версию тома, иначе спрашивает, чей текст
 * оставить, — поверх сама не пишет. Перед постановкой прогона запись доводится
 * до конца: служба берёт исходник на момент постановки, и собрать программу
 * без последней правки значило бы показать ошибку, которой в редакторе уже
 * нет. Уход со страницы дописывает правку запросом `keepalive`.
 *
 * **Номера строк прогона — от текста, из которого он собран** (`run.source`).
 * После правки они уже не те: `sourceLineOf` переводит номер сборки в номер
 * нынешнего исходника (строки сопоставляются по содержимому), а номер за концом
 * файла — так TASM отмечает неожиданный конец — прижимает к последней строке.
 */
import { useQueryClient } from '@tanstack/react-query'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type RefObject,
  type ReactNode,
} from 'react'

import { errorText, isApiError } from '@/api'
import { useJobStream, useMe } from '@/api/hooks'
import { useT } from '@/i18n'

import {
  asmKeys,
  fetchAsmProgram,
  fetchAsmSteps,
  holdAsmProgramRead,
  putAsmSettings,
  putAsmSource,
  requestAsmMemory,
  settingsOf,
  startAsmRun,
  useAsmProgram,
  useAsmRun,
  type AsmProgram,
} from './api'
import { focusTab, useDock, type DockApi } from './dock/useDock'
import type { AsmAnchor, AsmRunSummary, AsmSettings, AsmStep, AsmWindowId, Hex } from './types'

// ── договор с окнами ─────────────────────────────────────────────────────────

export interface AsmView {
  bits: 16 | 32
  radix: 'hex' | 'dec'
  keyBar: boolean
  traceSlider: boolean
}

export interface AsmContextValue {
  projectId: string
  programId: string
  program: { name: string; source: string; version: number } | undefined
  /** С отложенным сохранением и 409. */
  setSource(source: string): void
  settings: AsmSettings
  updateSettings(p: Partial<AsmSettings>): void
  run: AsmRunSummary | undefined
  runBusy: boolean
  buildAndRun(): void
  buildOnly(): void
  /** Исходник изменён после сборки показанного прогона: номера строк прогона — от прежнего текста. */
  buildStale: boolean
  /**
   * Номер строки сборки (сообщение TASM, листинг, шаг трассы) в нынешнем
   * исходнике. За концом файла — последняя строка; строка, которую после
   * правки не найти, — `null`.
   */
  sourceLineOf(line: number): number | null
  stepIndex: number
  step: AsmStep | undefined
  prevStep: AsmStep | undefined
  /** Из загруженных страниц; недостающую догружает сама. */
  getStep(i: number): AsmStep | undefined
  /**
   * Уже загруженные шаги, без запросов — для меток на дорожке ползунка.
   * Приехала страница — функция новая, по ней и пересчитываются метки.
   */
  loadedSteps(): Iterable<AsmStep>
  goto(i: number): void
  stepOver(): void
  stepInto(): void
  stepBack(): void
  runToCursor(): void
  runToBreakpoint(): void
  toStart(): void
  toEnd(): void
  cursorLine: number | null
  setCursorLine(l: number | null): void
  selection: AsmAnchor | null
  select(a: AsmAnchor | null): void
  view: AsmView
  setView(p: Partial<AsmView>): void
  openWindow(id: AsmWindowId, opts?: { focus?: boolean }): void
  /** Открывает окно «Агент». С `text` вопрос уходит сразу, без — подставляется в поле. */
  askAgent(anchor?: AsmAnchor | null, text?: string): void
  /** Открывает «Справку» на записи. */
  openDocs(token: string | null): void
  markUnread(id: AsmWindowId): void
  memory(step: number, ranges: { seg: Hex; off: Hex; len: number }[]): Promise<AsmRunSummary['dumps']>
  toast(text: string): void
  /**
   * Последний запрос к справке. `seq` растёт на каждый вызов, даже с тем же
   * словом: окно открывает запись по новому `seq`, и повторное F1 срабатывает.
   */
  docsRequest: { token: string | null; seq: number } | null
  /** Последний запрос к агенту; правило `seq` то же. */
  agentRequest: { anchor: AsmAnchor | null; text?: string; seq: number } | null
}

// ── своё каркаса ─────────────────────────────────────────────────────────────

export type AsmDialogId = 'find' | 'line' | 'addr' | 'watch' | 'buildOpts' | 'hotkeys' | 'rename' | 'saveAs'

export type SaveState = 'saved' | 'dirty' | 'saving' | 'conflict' | 'error'

export interface RunProgress {
  stage: string | null
  n: number | null
  of: number | null
}

export interface MenubarHandle {
  enter(): void
  leave(): void
  active(): boolean
}

export interface AsmUi {
  dock: DockApi
  dialog: AsmDialogId | null
  openDialog(id: AsmDialogId): void
  closeDialog(): void
  notice: { text: string; seq: number } | null
  saveState: SaveState
  saveError: string | null
  /** Отказ записи настроек прогона (ввод, лимит, точки, наблюдение). */
  settingsError: string | null
  conflict: { source: string; version: number } | null
  resolveConflict(keep: 'theirs' | 'mine'): void
  /** Довести запись исходника и настроек до конца. */
  flush(): Promise<boolean>
  progress: RunProgress
  runError: string | null
  /** Страница шагов не загрузилась; следующая удачная снимает. */
  traceError: string | null
  /** Есть ли трасса, по которой можно ходить. */
  traceReady: boolean
  lastIndex: number
  scanning: boolean
  toggleBreakpoint(line: number): void
  findQuery: string
  setFindQuery(q: string): void
  menubar: RefObject<MenubarHandle | null>
}

const AsmContext = createContext<AsmContextValue | null>(null)
const AsmUiContext = createContext<AsmUi | null>(null)

export function useAsm(): AsmContextValue {
  const ctx = useContext(AsmContext)
  if (!ctx) throw new Error('useAsm вызван вне AsmProvider')
  return ctx
}

export function useAsmUi(): AsmUi {
  const ctx = useContext(AsmUiContext)
  if (!ctx) throw new Error('useAsmUi вызван вне AsmProvider')
  return ctx
}

// ── постоянные ───────────────────────────────────────────────────────────────

/** Шагов в странице. Служба отдаёт до 2000; тысяча — полсекунды на медленной сети. */
const PAGE = 1000
const ПАУЗА_ИСХОДНИКА = 1000
const ПАУЗА_НАСТРОЕК = 600
/** Тело запроса `keepalive` браузеры ограничивают 64 КБ; с запасом на JSON вокруг текста. */
const KEEPALIVE_MAX = 60_000
const VIEW_KEY = 'koritsu.asm.view'

const ИДЁТ = new Set<AsmRunSummary['status']>(['queued', 'building', 'running'])
const С_ТРАССОЙ = new Set<AsmRunSummary['status']>(['done', 'step_limit', 'timeout', 'crashed'])

const DEFAULT_VIEW: AsmView = { bits: 16, radix: 'hex', keyBar: true, traceSlider: true }

function readView(): AsmView {
  try {
    const raw = localStorage.getItem(VIEW_KEY)
    if (!raw) return DEFAULT_VIEW
    const v = JSON.parse(raw) as Partial<AsmView>
    return {
      bits: v.bits === 32 ? 32 : 16,
      radix: v.radix === 'dec' ? 'dec' : 'hex',
      keyBar: v.keyBar !== false,
      traceSlider: v.traceSlider !== false,
    }
  } catch {
    return DEFAULT_VIEW
  }
}

function writeView(v: AsmView): void {
  try {
    localStorage.setItem(VIEW_KEY, JSON.stringify(v))
  } catch {
    // Вид доживёт до перезагрузки.
  }
}

const hex = (h: string | undefined) => (h ? parseInt(h, 16) : NaN)

/** Больше клеток таблица сопоставления не заводит: середина правки такого размера — уже другой текст. */
const СОПОСТАВЛЕНИЕ_МАКС = 4_000_000

/**
 * Куда уехали строки текста `a` в тексте `b`: `карта[i]` — номер строки в `b`
 * (с единицы) для строки `i + 1` из `a`, ноль — строки нет. Общие начало и
 * конец снимаются сразу, середина — наибольшей общей подпоследовательностью
 * строк. Строки между двумя совпавшими, где с обеих сторон их поровну, считаются
 * правленными на месте и сопоставляются по порядку: исправленная строка с
 * ошибкой — всё та же строка.
 */
function сопоставитьСтроки(a: string[], b: string[]): Int32Array {
  const карта = new Int32Array(a.length)
  let до = 0
  while (до < a.length && до < b.length && a[до] === b[до]) {
    карта[до] = до + 1
    до++
  }
  let после = 0
  while (после < a.length - до && после < b.length - до && a[a.length - 1 - после] === b[b.length - 1 - после]) {
    карта[a.length - 1 - после] = b.length - после
    после++
  }
  const n = a.length - до - после
  const m = b.length - до - после
  if (n > 0 && m > 0 && n * m <= СОПОСТАВЛЕНИЕ_МАКС) {
    // Длины общих хвостов: `д[i·w + j]` — для `a[до+i…]` и `b[до+j…]`. Длина не
    // больше min(n, m) ≤ 2000, шестнадцати бит хватает.
    const w = m + 1
    const д = new Uint16Array((n + 1) * w)
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        д[i * w + j] = a[до + i] === b[до + j] ? д[(i + 1) * w + j + 1]! + 1 : Math.max(д[(i + 1) * w + j]!, д[i * w + j + 1]!)
    let i = 0
    let j = 0
    while (i < n && j < m) {
      if (a[до + i] === b[до + j]) {
        карта[до + i] = до + j + 1
        i++
        j++
      } else if (д[(i + 1) * w + j]! >= д[i * w + j + 1]!) i++
      else j++
    }
  }
  let pa = -1
  let pb = -1
  for (let k = 0; k <= a.length; k++) {
    if (k < a.length && карта[k] === 0) continue
    const kb = k < a.length ? карта[k]! - 1 : b.length
    if (k - pa > 1 && k - pa === kb - pb) for (let d = 1; d < k - pa; d++) карта[pa + d] = pb + d + 1
    pa = k
    pb = kb
  }
  return карта
}

/** `sourceLineOf` для текста сборки `собран` и нынешнего `сейчас`; сопоставление считается при первом вопросе. */
function lineMapper(собран: string | null, сейчас: string): (line: number) => number | null {
  const now = сейчас.split('\n')
  const прижать = (n: number, всего: number) => Math.max(1, Math.min(всего, Math.round(n)))
  if (собран == null || собран === сейчас) return (n) => прижать(n, now.length)
  const was = собран.split('\n')
  let карта: Int32Array | null = null
  return (n) => {
    карта ??= сопоставитьСтроки(was, now)
    return карта[прижать(n, was.length) - 1] || null
  }
}

// ── провайдер ────────────────────────────────────────────────────────────────

export function AsmProvider({
  projectId,
  programId,
  program: loaded,
  children,
}: {
  projectId: string
  programId: string
  program: AsmProgram
  children: ReactNode
}) {
  const t = useT()
  const qc = useQueryClient()
  const me = useMe()
  const dock = useDock(me.data?.id)
  const programQ = useAsmProgram(projectId, programId)
  const name = programQ.data?.name ?? loaded.name

  // ── уведомление в строке ──
  const [notice, setNotice] = useState<{ text: string; seq: number } | null>(null)
  const toast = useCallback((text: string) => {
    setNotice((was) => ({ text, seq: (was?.seq ?? 0) + 1 }))
  }, [])
  useEffect(() => {
    if (!notice) return
    const id = setTimeout(() => setNotice(null), 2600)
    return () => clearTimeout(id)
  }, [notice])

  // ── исходник ──
  const [source, setSourceState] = useState(loaded.source)
  const [version, setVersion] = useState(loaded.version)
  const [saveState, setSaveState] = useState<SaveState>('saved')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<{ source: string; version: number } | null>(null)
  /** `правлено` — была ли в этой вкладке правка: без неё писать на том нечего. */
  const исходник = useRef({ text: loaded.source, version: loaded.version, saved: loaded.source, правлено: false })
  const таймерИсходника = useRef<ReturnType<typeof setTimeout> | null>(null)
  const идётЗапись = useRef<Promise<void> | null>(null)
  const конфликт = useRef(false)
  const saveStateRef = useRef(saveState)
  saveStateRef.current = saveState

  /** Взять текст и версию тома как свои: правки, ждущей записи, больше нет. */
  const takeVolume = useCallback(
    (text: string, ver: number) => {
      const s = исходник.current
      конфликт.current = false
      s.text = text
      s.saved = text
      s.version = ver
      s.правлено = false
      setVersion(ver)
      setConflict(null)
      setSourceState(text)
      setSaveState('saved')
      setSaveError(null)
      qc.setQueryData<AsmProgram>(asmKeys.program(projectId, programId), (было) =>
        было ? { ...было, source: text, version: ver } : было,
      )
    },
    [projectId, programId, qc],
  )

  const saveSource = useCallback(
    (opts: { keepalive?: boolean } = {}): Promise<void> => {
      const работа = (async () => {
        // Страница уходит, а прошлая запись ещё летит: ждать её ответа некогда,
        // а вторая с той же версией получила бы 409. Такую правку бережёт вопрос
        // `beforeunload`, и таймер остаётся — если страница вернётся из кэша
        // браузера, правка уедет обычным путём.
        if (opts.keepalive && идётЗапись.current) return
        if (таймерИсходника.current) clearTimeout(таймерИсходника.current)
        таймерИсходника.current = null
        // Записи идут по одной: вторая с той же версией получила бы 409 от первой.
        while (идётЗапись.current) await идётЗапись.current
        const s = исходник.current
        if (!s.правлено || конфликт.current || s.text === s.saved) return
        const text = s.text
        setSaveState('saving')
        const keepalive = !!opts.keepalive && new TextEncoder().encode(text).length < KEEPALIVE_MAX
        const запись = putAsmSource(projectId, programId, text, s.version, { keepalive })
          .then((ответ) => {
            s.version = ответ.version
            s.saved = text
            setVersion(ответ.version)
            setSaveError(null)
            setSaveState(s.text === text ? 'saved' : 'dirty')
          })
          .catch(async (беда: unknown) => {
            if (isApiError(беда) && беда.status === 409) {
              конфликт.current = true
              setSaveState('conflict')
              try {
                // Это чтение — изнутри записи, которую ждут остальные чтения.
                const свежая = await fetchAsmProgram(projectId, programId, { waitWrites: false })
                const my = исходник.current
                // На томе ровно наш текст или своей незаписанной правки уже нет —
                // спрашивать не о чем.
                if (свежая.source === my.text || my.text === my.saved) takeVolume(свежая.source, свежая.version)
                else setConflict({ source: свежая.source, version: свежая.version })
              } catch (e) {
                setSaveError(errorText(e))
              }
              return
            }
            setSaveState('error')
            setSaveError(errorText(беда))
          })
        идётЗапись.current = запись.finally(() => {
          идётЗапись.current = null
        })
        await запись
        // Пока летел ответ, человек мог дописать: такая правка уезжает следующей.
        if (!конфликт.current && исходник.current.text !== исходник.current.saved && saveStateRef.current !== 'error')
          таймерИсходника.current = setTimeout(() => void saveSource(), ПАУЗА_ИСХОДНИКА)
      })()
      holdAsmProgramRead(programId, работа)
      return работа
    },
    [projectId, programId, takeVolume],
  )

  const setSource = useCallback(
    (text: string) => {
      const s = исходник.current
      if (text === s.text) return
      s.text = text
      s.правлено = true
      setSourceState(text)
      if (конфликт.current) return
      setSaveState(text === s.saved ? 'saved' : 'dirty')
      if (таймерИсходника.current) clearTimeout(таймерИсходника.current)
      таймерИсходника.current = setTimeout(() => void saveSource(), ПАУЗА_ИСХОДНИКА)
    },
    [saveSource],
  )

  const resolveConflict = useCallback(
    (keep: 'theirs' | 'mine') => {
      if (!conflict) return
      if (keep === 'theirs') {
        takeVolume(conflict.source, conflict.version)
        return
      }
      const s = исходник.current
      конфликт.current = false
      s.version = conflict.version
      setVersion(conflict.version)
      setConflict(null)
      setSaveState('dirty')
      void saveSource()
    },
    [conflict, takeVolume, saveSource],
  )

  // Уход с незаписанной правкой. `beforeunload` спрашивает, уходить ли, а сама
  // запись — на `pagehide` запросом `keepalive`: обычный запрос браузер оборвал
  // бы вместе со страницей. Уход внутри сайта (размонтирование) дописывает
  // правку обычной записью, и страница, открытая снова, дождётся её перед
  // чтением программы.
  useEffect(() => {
    const перед = (e: BeforeUnloadEvent) => {
      const s = исходник.current
      if (!s.правлено || s.text === s.saved || конфликт.current) return
      e.preventDefault()
    }
    const уход = () => void saveSource({ keepalive: true })
    window.addEventListener('beforeunload', перед)
    window.addEventListener('pagehide', уход)
    return () => {
      window.removeEventListener('beforeunload', перед)
      window.removeEventListener('pagehide', уход)
      void saveSource()
    }
  }, [saveSource])

  // ── настройки ──
  const [settings, setSettings] = useState<AsmSettings>(() => settingsOf(loaded))
  const [settingsError, setSettingsError] = useState<string | null>(null)
  // `sent` — настройки, которые уже лежат на томе. Уезжают только отличные от
  // них, поэтому открытие страницы и повтор того же значения ничего не пишут.
  const настройки = useRef({ value: settings, sent: JSON.stringify(settings) })
  const таймерНастроек = useRef<ReturnType<typeof setTimeout> | null>(null)

  const saveSettings = useCallback(async (): Promise<boolean> => {
    if (таймерНастроек.current) clearTimeout(таймерНастроек.current)
    таймерНастроек.current = null
    const н = настройки.current
    const json = JSON.stringify(н.value)
    if (json === н.sent) return true
    const было = н.sent
    н.sent = json
    try {
      await putAsmSettings(projectId, programId, н.value)
      setSettingsError(null)
      return true
    } catch (беда) {
      if (н.sent === json) н.sent = было
      setSettingsError(errorText(беда))
      return false
    }
  }, [projectId, programId])

  const updateSettings = useCallback(
    (p: Partial<AsmSettings>) => {
      const was = настройки.current.value
      const next = { ...was, ...p }
      if (JSON.stringify(next) === JSON.stringify(was)) return
      настройки.current.value = next
      setSettings(next)
      if (таймерНастроек.current) clearTimeout(таймерНастроек.current)
      таймерНастроек.current = setTimeout(() => void saveSettings(), ПАУЗА_НАСТРОЕК)
    },
    [saveSettings],
  )

  useEffect(() => () => void saveSettings(), [saveSettings])

  const flush = useCallback(async () => {
    await saveSource()
    const ok = await saveSettings()
    return ok && !конфликт.current && исходник.current.text === исходник.current.saved
  }, [saveSource, saveSettings])

  const toggleBreakpoint = useCallback(
    (line: number) => {
      const bps = настройки.current.value.breakpoints
      updateSettings({
        breakpoints: bps.includes(line) ? bps.filter((x) => x !== line) : [...bps, line].sort((a, b) => a - b),
      })
    },
    [updateSettings],
  )

  // ── прогон ──
  const [runNo, setRunNo] = useState<number | null>(loaded.last_run_no ?? null)
  const runQ = useAsmRun(projectId, programId, runNo)
  const run = runQ.data
  const [jobId, setJobId] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const идётПрогон = !!run && ИДЁТ.has(run.status)
  const stream = useJobStream(jobId ?? (идётПрогон ? run?.job_id : null))

  const progress = useMemo<RunProgress>(() => {
    // Ход задания — кадр `progress` очереди `{step, total, note}`; этап сборки
    // (`tasm` → `tlink` → `trace`) служба кладёт в `note`, шаги трассы — в `step`/`total`.
    let p: RunProgress = { stage: null, n: null, of: null }
    for (const кадр of stream.events) {
      if (кадр.kind !== 'progress') continue
      const d = кадр.data as { step?: unknown; total?: unknown; note?: unknown }
      if (typeof d?.note !== 'string' || !d.note) continue
      const n = typeof d.step === 'number' ? d.step : null
      const of = typeof d.total === 'number' ? d.total : null
      p = { stage: d.note, n, of }
    }
    return p
  }, [stream.events])

  // Смена этапа меняет и сводку (статус «сборка» → «трасса»): перечитываем.
  useEffect(() => {
    if (runNo && progress.stage) void runQ.refetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progress.stage])

  // Конец задания — финальная сводка и окно, где смотреть результат.
  const закрытыйПрогон = useRef<string | null>(null)
  useEffect(() => {
    const id = jobId ?? run?.job_id ?? null
    if (!id || !stream.done || закрытыйПрогон.current === id) return
    закрытыйПрогон.current = id
    setJobId(null)
    const провал = stream.job?.status === 'failed'
    if (провал) {
      const беда = (stream.job?.error ?? {}) as { message?: string }
      setRunError(беда.message || t('asm.status.runFailed'))
    }
    void runQ.refetch().then(({ data }) => {
      if (!data) return
      // Беда показывается на месте: статус — в строке меню, лог и текст отказа —
      // в «Сборке», которая открывается сама; всплывающего сообщения нет.
      if (провал || data.status === 'build_error' || (!data.build?.ok && data.status !== 'done')) {
        dock.show('build', { focus: true })
      } else if (С_ТРАССОЙ.has(data.status)) {
        dock.show('output', { ifOpen: true })
        dock.markUnread('output')
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.done, jobId, run?.job_id])

  // Сводка в работе, а потока нет (служба не назвала задание): спрашиваем сами.
  useEffect(() => {
    if (!идётПрогон || run?.job_id) return
    const id = setInterval(() => void runQ.refetch(), 1500)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [идётПрогон, run?.job_id])

  const runBusy = starting || (!!jobId && !stream.done) || идётПрогон

  const start = useCallback(
    async (mode: 'build' | 'run') => {
      if (runBusy) return
      setStarting(true)
      setRunError(null)
      try {
        if (!(await flush())) {
          setRunError(t('asm.status.saveFirst'))
          return
        }
        const ответ = await startAsmRun(projectId, programId, mode)
        закрытыйПрогон.current = null
        setJobId(ответ.job_id)
        setRunNo(ответ.run_no)
        dock.show('build', { ifOpen: true })
        void qc.invalidateQueries({ queryKey: asmKeys.programsAll })
      } catch (беда) {
        setRunError(errorText(беда))
      } finally {
        setStarting(false)
      }
    },
    [runBusy, flush, projectId, programId, dock, qc, t],
  )

  const buildAndRun = useCallback(() => void start('run'), [start])
  const buildOnly = useCallback(() => void start('build'), [start])

  // ── строки сборки в нынешнем исходнике ──
  const собранИз = run?.build ? (run.source ?? null) : null
  const buildStale = собранИз != null && собранИз !== source
  const sourceLineOf = useMemo(() => lineMapper(собранИз, source), [собранИз, source])

  // ── трасса: страницы шагов ──
  const traceReady = !!run && С_ТРАССОЙ.has(run.status) && run.totals.steps > 0
  const traceKey = traceReady && run ? `${run.run_no}:${run.totals.steps}` : ''
  const кэш = useRef<{ key: string; steps: Map<number, AsmStep>; pages: Map<number, Promise<void>> }>({
    key: '',
    steps: new Map(),
    pages: new Map(),
  })
  if (кэш.current.key !== traceKey) кэш.current = { key: traceKey, steps: new Map(), pages: new Map() }
  const [stepsTick, bump] = useReducer((x: number) => x + 1, 0)
  // Последний номер шага: `totals.steps`, пока страница не показала, что шагов меньше.
  const [lastFix, setLastFix] = useState<{ key: string; last: number } | null>(null)
  const [traceError, setTraceError] = useState<string | null>(null)
  const lastIndex = !traceReady || !run ? 0 : lastFix?.key === traceKey ? lastFix.last : run.totals.steps

  const inGap = useCallback(
    (i: number) => {
      const tr = run?.truncated
      return !!tr && i >= tr.head && i < tr.head + tr.skipped
    },
    [run?.truncated],
  )

  const ensurePage = useCallback(
    (page: number): Promise<void> => {
      const c = кэш.current
      const есть = c.pages.get(page)
      if (есть) return есть
      if (!traceReady || !run) return Promise.resolve()
      const from = page * PAGE
      const to = Math.min(from + PAGE, lastIndex + 1)
      if (to <= from) return Promise.resolve()
      const key = c.key
      const p = fetchAsmSteps(projectId, programId, run.run_no, from, to)
        .then((ответ) => {
          if (кэш.current.key !== key) return
          let max = -1
          for (const s of ответ.steps) {
            кэш.current.steps.set(s.i, s)
            max = Math.max(max, s.i)
          }
          // Последняя страница короче, чем обещала сводка: запоминаем настоящий конец.
          if (to === lastIndex + 1 && max >= 0 && max < lastIndex && !inGap(lastIndex))
            setLastFix({ key, last: max })
          setTraceError(null)
          bump()
        })
        .catch((беда: unknown) => {
          // Страницу можно попросить снова: неудача не запоминается. Отказ виден
          // в строке статуса, пока следующая страница не приедет.
          кэш.current.pages.delete(page)
          setTraceError(errorText(беда))
        })
      c.pages.set(page, p)
      return p
    },
    [traceReady, run, lastIndex, projectId, programId, inGap],
  )

  const getStep = useCallback(
    (i: number): AsmStep | undefined => {
      if (!traceReady || i < 0 || i > lastIndex || inGap(i)) return undefined
      const s = кэш.current.steps.get(i)
      if (!s) {
        const page = Math.floor(i / PAGE)
        // Запрос — не во время отрисовки: `getStep` зовут из render окон.
        if (!кэш.current.pages.has(page)) queueMicrotask(() => void ensurePage(page))
      }
      return s
    },
    // `stepsTick` — чтобы окна, взявшие функцию в зависимости, увидели приехавшую страницу.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [traceReady, lastIndex, inGap, ensurePage, stepsTick],
  )

  const loadedSteps = useCallback(
    (): Iterable<AsmStep> => кэш.current.steps.values(),
    // Кэш — ссылка: новую функцию дают новая трасса и приехавшая страница.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [traceKey, stepsTick],
  )

  const loadStep = useCallback(
    async (i: number): Promise<AsmStep | undefined> => {
      if (!traceReady || i < 0 || i > lastIndex || inGap(i)) return undefined
      const s = кэш.current.steps.get(i)
      if (s) return s
      await ensurePage(Math.floor(i / PAGE))
      return кэш.current.steps.get(i)
    },
    [traceReady, lastIndex, inGap, ensurePage],
  )

  const [stepIndex, setStepIndex] = useState(0)
  // Новая трасса — стоим перед первой командой.
  useEffect(() => {
    setStepIndex(0)
  }, [traceKey])

  const clamp = useCallback(
    (i: number, dir: 1 | -1 = 1) => {
      let k = Math.max(0, Math.min(lastIndex, Math.round(i)))
      const tr = run?.truncated
      if (tr && inGap(k)) k = dir > 0 ? Math.min(lastIndex, tr.head + tr.skipped) : tr.head - 1
      return Math.max(0, k)
    },
    [lastIndex, run?.truncated, inGap],
  )

  const сканирование = useRef(0)
  const [scanning, setScanning] = useState(false)

  const goto = useCallback(
    (i: number) => {
      if (!traceReady) return
      сканирование.current++
      setScanning(false)
      setStepIndex((was) => clamp(i, i >= was ? 1 : -1))
    },
    [traceReady, clamp],
  )

  const нетТрассы = useCallback(() => {
    toast(runBusy ? t('asm.status.traceWriting') : t('asm.status.noTrace'))
  }, [toast, runBusy, t])

  /** Первый шаг после `from`, подходящий под условие, с догрузкой страниц. */
  const scan = useCallback(
    async (from: number, pred: (s: AsmStep) => boolean): Promise<number | null> => {
      const жетон = ++сканирование.current
      setScanning(true)
      try {
        for (let i = clamp(from); i <= lastIndex; i++) {
          if (inGap(i)) {
            i = clamp(i) - 1
            continue
          }
          const s = кэш.current.steps.get(i) ?? (await loadStep(i))
          if (сканирование.current !== жетон) return null
          if (s && pred(s)) return i
        }
        return null
      } finally {
        if (сканирование.current === жетон) setScanning(false)
      }
    },
    [clamp, lastIndex, inGap, loadStep],
  )

  const stepInto = useCallback(() => {
    if (!traceReady) return нетТрассы()
    if (stepIndex >= lastIndex) {
      toast(run?.status === 'done' ? t('asm.status.programEnded') : t('asm.status.traceEnd'))
      return
    }
    goto(stepIndex + 1)
  }, [traceReady, нетТрассы, stepIndex, lastIndex, goto, toast, run?.status, t])

  const stepBack = useCallback(() => {
    if (!traceReady) return нетТрассы()
    if (stepIndex <= 0) {
      toast(t('asm.status.traceStart'))
      return
    }
    goto(stepIndex - 1)
  }, [traceReady, нетТрассы, stepIndex, goto, toast, t])

  const stepOver = useCallback(() => {
    if (!traceReady) return нетТрассы()
    void (async () => {
      const cur = await loadStep(stepIndex)
      const команда = cur?.next?.asm ?? ''
      if (!cur || !/^\s*call\b/i.test(команда)) return stepInto()
      // После CALL указатель стека ниже; вернулся — значит, подпрограмма кончилась.
      const sp = hex(cur.reg.sp)
      const k = await scan(stepIndex + 1, (s) => hex(s.reg.sp) >= sp)
      if (k === null) {
        goto(lastIndex)
        toast(t('asm.status.noReturn'))
      } else goto(k)
    })()
  }, [traceReady, нетТрассы, loadStep, stepIndex, stepInto, scan, goto, lastIndex, toast, t])

  const [cursorLine, setCursorLine] = useState<number | null>(null)
  const [selection, setSelection] = useState<AsmAnchor | null>(null)

  const runToCursor = useCallback(() => {
    if (!traceReady) return нетТрассы()
    if (cursorLine == null) {
      toast(t('asm.status.noCursor'))
      return
    }
    const line = cursorLine
    void scan(stepIndex + 1, (s) => s.next?.line === line).then((k) => {
      if (k === null) toast(t('asm.status.lineNotReached', { line }))
      else goto(k)
    })
  }, [traceReady, нетТрассы, cursorLine, scan, stepIndex, goto, toast, t])

  const runToBreakpoint = useCallback(() => {
    if (!traceReady) return нетТрассы()
    const bps = new Set(settings.breakpoints)
    void scan(stepIndex + 1, (s) => s.next?.line != null && bps.has(s.next.line)).then((k) => {
      if (k === null) {
        goto(lastIndex)
        if (bps.size) toast(t('asm.status.noBreakpointAhead'))
      } else goto(k)
    })
  }, [traceReady, нетТрассы, settings.breakpoints, scan, stepIndex, goto, lastIndex, toast, t])

  const toStart = useCallback(() => (traceReady ? goto(0) : нетТрассы()), [traceReady, goto, нетТрассы])
  const toEnd = useCallback(() => (traceReady ? goto(lastIndex) : нетТрассы()), [traceReady, goto, lastIndex, нетТрассы])

  // ── вид, окна, запросы к агенту и справке ──
  const [view, setViewState] = useState<AsmView>(readView)
  const setView = useCallback((p: Partial<AsmView>) => {
    setViewState((was) => {
      const next = { ...was, ...p }
      writeView(next)
      return next
    })
  }, [])

  const openWindow = useCallback(
    (id: AsmWindowId, opts?: { focus?: boolean }) => {
      const focus = opts?.focus ?? true
      dock.show(id, { focus })
      if (focus) focusTab(id)
    },
    [dock],
  )

  const [docsRequest, setDocsRequest] = useState<AsmContextValue['docsRequest']>(null)
  const [agentRequest, setAgentRequest] = useState<AsmContextValue['agentRequest']>(null)
  const selectionRef = useRef(selection)
  selectionRef.current = selection

  const openDocs = useCallback(
    (token: string | null) => {
      setDocsRequest((was) => ({ token, seq: (was?.seq ?? 0) + 1 }))
      openWindow('docs', { focus: true })
    },
    [openWindow],
  )

  const askAgent = useCallback(
    (anchor?: AsmAnchor | null, text?: string) => {
      if (anchor) setSelection(anchor)
      const якорь = anchor ?? selectionRef.current
      setAgentRequest((was) => ({
        anchor: якорь,
        ...(text ? { text } : {}),
        seq: (was?.seq ?? 0) + 1,
      }))
      openWindow('agent', { focus: true })
    },
    [openWindow],
  )

  const memory = useCallback(
    (step: number, ranges: { seg: Hex; off: Hex; len: number }[]) => {
      if (!run) return Promise.reject(new Error('no run'))
      return requestAsmMemory(projectId, programId, run.run_no, step, ranges)
    },
    [run, projectId, programId],
  )

  // ── каркас ──
  const [dialog, setDialog] = useState<AsmDialogId | null>(null)
  const [findQuery, setFindQuery] = useState('')
  const menubar = useRef<MenubarHandle | null>(null)

  const step = getStep(stepIndex)
  const prevStep = stepIndex > 0 ? getStep(stepIndex - 1) : undefined

  const value = useMemo<AsmContextValue>(
    () => ({
      projectId,
      programId,
      program: { name, source, version },
      setSource,
      settings,
      updateSettings,
      run,
      runBusy,
      buildAndRun,
      buildOnly,
      buildStale,
      sourceLineOf,
      stepIndex,
      step,
      prevStep,
      getStep,
      loadedSteps,
      goto,
      stepOver,
      stepInto,
      stepBack,
      runToCursor,
      runToBreakpoint,
      toStart,
      toEnd,
      cursorLine,
      setCursorLine,
      selection,
      select: setSelection,
      view,
      setView,
      openWindow,
      askAgent,
      openDocs,
      markUnread: dock.markUnread,
      memory,
      toast,
      docsRequest,
      agentRequest,
    }),
    [
      projectId, programId, name, source, version, setSource, settings, updateSettings, run, runBusy,
      buildAndRun, buildOnly, buildStale, sourceLineOf, stepIndex, step, prevStep, getStep, loadedSteps, goto, stepOver, stepInto, stepBack,
      runToCursor, runToBreakpoint, toStart, toEnd, cursorLine, selection, view, setView, openWindow,
      askAgent, openDocs, dock.markUnread, memory, toast, docsRequest, agentRequest,
    ],
  )

  const ui = useMemo<AsmUi>(
    () => ({
      dock,
      dialog,
      openDialog: setDialog,
      closeDialog: () => setDialog(null),
      notice,
      saveState,
      saveError,
      settingsError,
      conflict,
      resolveConflict,
      flush,
      progress,
      runError,
      traceError,
      traceReady,
      lastIndex,
      scanning,
      toggleBreakpoint,
      findQuery,
      setFindQuery,
      menubar,
    }),
    [
      dock, dialog, notice, saveState, saveError, settingsError, conflict, resolveConflict, flush, progress,
      runError, traceError, traceReady, lastIndex, scanning, toggleBreakpoint, findQuery,
    ],
  )

  return (
    <AsmUiContext.Provider value={ui}>
      <AsmContext.Provider value={value}>{children}</AsmContext.Provider>
    </AsmUiContext.Provider>
  )
}
