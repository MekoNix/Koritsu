/**
 * useBoardCheck — одна просьба к репетитору: постановка в очередь, поток
 * событий, ответ.
 *
 * Три кнопки экрана — **одно** задание очереди (`board_check`) с полем режима, а
 * не три договора: сверять ответ со сценой, считать цену и отменять прогон надо
 * одинаково во всех трёх случаях, и разведённые по разным заданиям они разошлись
 * бы на первой же правке.
 *
 * **Проверка односнимковая.** Снимок сцены берётся службой на старте, и
 * написанное после запуска в этот прогон не попадает. Поэтому здесь помнится
 * версия сцены, с которой прогон начинали: как только на доске стало новее,
 * вердикт гаснет, а замечания бледнеют — они относятся к прежней записи.
 *
 * **Ход прогона берётся из потока, а не опросом.** События `step_checked`
 * приезжают по одному на строку, и их ровно столько, сколько строк на доске.
 * Разбор потока — чистая свёртка по кадрам, а не накопление в `ref`: поток
 * переподключается с последнего события, после чего кадры приезжают те же
 * самые, и накопитель показал бы строку дважды.
 *
 * **Тоста на упавшее задание здесь нет.** Провал тостит оболочка по коду из
 * уведомления; беда остаётся на экране строкой — тост уходит через шесть секунд,
 * а человек смотрит именно сюда.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError, errorSaid, errorText, keys } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useCancelJob } from '@/features/agent/data'
import { useEnqueueJob } from '@/features/projects/data'

import {
  BOARD_CHECK,
  EV_STEP_CHECKED,
  EV_TEXT,
  type BoardCheckResult,
  type BoardLevel,
  type BoardMode,
  type StepVerdict,
} from './types'

/**
 * Сколько подсказок подряд даётся по одной доске.
 *
 * Две: первая говорит, что рассмотреть, вторая называет приём. Третья — это уже
 * решение, а человек, у которого решение в одном нажатии, до второго шага не
 * дойдёт. Объяснение подробнее просится словами.
 */
export const HINT_STEPS = 2

export type Ask = {
  mode: BoardMode
  /** Шаг, по которому просят подсказку; для прочих режимов не читается. */
  step?: string
  /** Версия сцены, по которой человек нажал кнопку. */
  sceneVersion: number
  /** Строка просьбы, если человек её написал. Пустая не уезжает вовсе. */
  wishes?: string
  /** Сообщение переписки: режим `chat`. */
  message?: string
  /** Короткие имена строк, которые приложить; нет — все. */
  lines?: string[]
}

export type BoardCheckState = {
  /** Идёт ли прогон прямо сейчас: на месте трёх кнопок — «Остановить». */
  running: boolean
  /** Вид идущей просьбы; `null` — прогона нет. */
  mode: BoardMode | null
  jobId: string | null
  /** Вердикты по строкам, приехавшие потоком, — пока ответа целиком ещё нет. */
  progress: StepVerdict[]
  /** Человеческий текст ответа из потока: он приходит раньше карточки задания. */
  text: string
  /** Ответ прогона, сверенный службой со сценой. */
  result: BoardCheckResult | null
  /** Ответ относится к прежней записи: доску правили после запуска. */
  stale: boolean
  /** Сколько подсказок подряд уже спросили. */
  hints: number
  error: string | null
  errorRaw: string | null
  /**
   * Код беды как его назвала служба; `null` — беды нет.
   *
   * Нужен не для показа — человеку показывается текст, — а для того, чтобы
   * страница могла починить беду сама. `scene_stale` чинится пересборкой строк
   * и повтором, и делать это руками человеку незачем.
   */
  errorCode: string | null
  /** Прошлый прогон остановлен человеком. Сделанное сохранено. */
  stopped: boolean
  stopping: boolean
  ask: (опрос: Ask) => void
  stop: () => void
  /** Забыть ответ: например, когда доску начали решать заново. */
  clear: () => void
}

/**
 * @param projectId работа, которой принадлежит доска
 * @param boardId   доска: она же решение, и она же `run_id` задания
 * @param endpoint  пресет модели; `null` — платить нечем, кнопки не нажимаются
 * @param sceneVersion текущая версия сцены: по ней гаснет вердикт
 */
export function useBoardCheck(
  projectId: string,
  boardId: string,
  endpoint: string | null,
  sceneVersion: number,
): BoardCheckState {
  const qc = useQueryClient()
  const enqueue = useEnqueueJob()
  // Отмена задания общая для всей очереди, и своего хука у области нет
  // намеренно: второй такой же рядом с первым — это два кэша одного действия.
  const cancel = useCancelJob()

  const [running, setRunning] = useState<{ id: string; mode: BoardMode } | null>(null)
  const [result, setResult] = useState<BoardCheckResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [errorRaw, setErrorRaw] = useState<string | null>(null)
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [stopped, setStopped] = useState(false)
  const [hints, setHints] = useState(0)
  /** Версия сцены на старте прогона: с ней сравнивается текущая. */
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const stream = useJobStream(running?.id)
  // Чтобы не показать конец одного задания дважды: поток закрывается, карточка
  // перечитывается, и `done` становится истиной не один раз.
  const закрыто = useRef<string | null>(null)

  const progress = useMemo(() => {
    const шаги: StepVerdict[] = []
    for (const кадр of stream.events) {
      if (кадр.kind !== EV_STEP_CHECKED) continue
      шаги.push(кадр.data as StepVerdict)
    }
    return шаги
  }, [stream.events])

  const text = useMemo(() => {
    const куски: string[] = []
    for (const кадр of stream.events) {
      if (кадр.kind !== EV_TEXT) continue
      const строка = (кадр.data as { text?: unknown })?.text
      if (typeof строка === 'string' && строка) куски.push(строка)
    }
    return куски.join('\n')
  }, [stream.events])

  const идёт = !!running && !stream.done

  useEffect(() => {
    if (!running || !stream.done || закрыто.current === running.id) return
    закрыто.current = running.id
    // Перечитывается всё, что мог изменить прогон: карточка доски (её проверяли)
    // и остаток месяца. Чистовик прогон не трогает — доску правит только человек.
    void qc.invalidateQueries({ queryKey: keys.board.boards(projectId) })
    void qc.invalidateQueries({ queryKey: keys.usage })
    if (stream.job?.status === 'cancelled') {
      // Отмена — не беда: человек сам попросил остановиться, и красная строка на
      // его собственное действие читается как поломка.
      setStopped(true)
    } else if (stream.job?.status !== 'done') {
      const беда = (stream.job?.error ?? {}) as { code?: string; message?: string }
      const сказано = errorSaid(new ApiError(беда.code || 'unknown', беда.message || ''))
      setError(сказано.text)
      setErrorRaw(сказано.raw || null)
      setErrorCode(беда.code || 'unknown')
    } else {
      const ответ = stream.job?.result
      // Переписка перечитывается ДО того, как ответ объявляется полученным:
      // страница снимает своё «ждём ответа» по ответу, и снятое раньше, чем
      // приехала запись с тома, на миг оставило бы разговор без последней пары.
      void qc.invalidateQueries({ queryKey: keys.board.chat(projectId, boardId) }).finally(() => {
        if (ответ) setResult(ответ as BoardCheckResult)
        setRunning(null)
      })
      return
    }
    setRunning(null)
  }, [running, stream.done, stream.job, projectId, boardId, qc])

  const ask = useCallback(
    ({ mode, step = '', sceneVersion: версия, wishes = '', message = '', lines }: Ask) => {
      if (!endpoint || !boardId) return
      setError(null)
      setErrorRaw(null)
      setErrorCode(null)
      setStopped(false)
      setResult(null)
      setStartedAt(версия)
      // Вторая подсказка идёт глубже первой: называет приём, но не выполняет
      // его. Третьей ступени нет — после неё осталось бы только решение.
      const уровень: BoardLevel =
        mode === 'hint' && hints >= 1 ? 'solution' : mode === 'hint' ? 'hint' : 'explain'
      if (mode === 'hint') setHints((было) => Math.min(было + 1, HINT_STEPS))
      else setHints(0)
      enqueue.mutate(
        {
          kind: BOARD_CHECK,
          projectId,
          payload: {
            run_id: boardId,
            endpoint,
            mode,
            level: уровень,
            step,
            scene_version: версия,
            // Пустая просьба не уезжает: тогда тело задания — ровно то, что
            // объявлено договором, без единого лишнего поля.
            ...(wishes.trim() ? { wishes: wishes.trim() } : {}),
            ...(message.trim() ? { message: message.trim() } : {}),
            ...(lines?.length ? { lines } : {}),
          },
        },
        {
          onSuccess: (задание) => {
            закрыто.current = null
            setRunning({ id: задание.id, mode })
          },
          onError: (беда) => {
            setError(errorText(беда))
            setErrorCode(String((беда as { code?: string })?.code ?? 'unknown'))
          },
        },
      )
    },
    [boardId, endpoint, enqueue, hints, projectId],
  )

  /**
   * Остановка — просьба, а не выключатель: ждущее задание служба снимает сразу,
   * а идущее останавливается на ближайшей проверке. Поэтому кнопка гаснет не по
   * ответу службы, а по концу потока: до него прогон ещё идёт.
   */
  const stop = useCallback(() => {
    if (!running) return
    cancel.mutate(running.id, { onError: (беда) => setError(errorText(беда)) })
  }, [cancel, running])

  const clear = useCallback(() => {
    setResult(null)
    setError(null)
    setErrorRaw(null)
    setErrorCode(null)
    setStopped(false)
    setStartedAt(null)
    setHints(0)
  }, [])

  return {
    running: идёт,
    mode: идёт ? (running?.mode ?? null) : null,
    jobId: running?.id ?? null,
    progress,
    text,
    result,
    stale: startedAt !== null && sceneVersion > startedAt,
    hints,
    error,
    errorRaw,
    errorCode,
    stopped,
    stopping: cancel.isPending,
    ask,
    stop,
    clear,
  }
}
