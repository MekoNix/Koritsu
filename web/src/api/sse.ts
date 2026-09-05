/**
 * api/sse — чтение потоков службы (`text/event-stream`) с дочитыванием с обрыва.
 *
 * **Почему не `EventSource`.** Служба именует кадры (`event: <вид>`), а
 * `EventSource` отдаёт в `onmessage` только безымянные: чтобы поймать
 * именованный, надо заранее знать его имя и подписаться на каждое. Виды кадров
 * задания пишут обработчики службы, список открыт — значит подписаться на все
 * нельзя в принципе, и половина потока молча терялась бы. Плюс `EventSource`
 * не умеет ни задать заголовок, ни закрыться по нашему условию: поток задания
 * закрывается сам на конце задания, а браузер считает это обрывом и
 * переподключается вечно.
 *
 * Поэтому поток читается `fetch`'ем: полный разбор кадров, свой заголовок
 * `Last-Event-ID` и своя политика переподключения.
 *
 * **Дочитывание** (решение владельца: «SSE переподключается сам с последнего
 * события»). Идентификатор последнего кадра запоминается и уходит заголовком
 * `Last-Event-ID` на переподключении — служба продолжает ровно с него
 * (`packages/api/events/routes.py`). Пауза между попытками растёт, чтобы упавшая
 * служба не получила от каждой вкладки по запросу в секунду.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type SseFrame = {
  /** `id:` кадра. У задания — номер по порядку, у потока человека — время ISO. */
  id: string | null
  /** `event:` — вид кадра. Безымянный кадр приходит как `message`. */
  kind: string
  /** `data:` уже разобранная из JSON; не JSON — строка как есть. */
  data: unknown
}

export type SseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'

/** Паузы перед попытками переподключения, мс. Дальше — последняя, без роста. */
const BACKOFF = [500, 1000, 2000, 5000, 10000]

/** Разобрать один кадр SSE (кусок между пустыми строками). */
function parseFrame(chunk: string): SseFrame | null {
  let id: string | null = null
  let kind = 'message'
  const data: string[] = []
  for (const rawLine of chunk.split('\n')) {
    if (!rawLine || rawLine.startsWith(':')) continue // комментарий-пульс
    const colon = rawLine.indexOf(':')
    const field = colon < 0 ? rawLine : rawLine.slice(0, colon)
    // По спецификации после двоеточия съедается один пробел, и только один.
    let value = colon < 0 ? '' : rawLine.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'id') id = value
    else if (field === 'event') kind = value
    else if (field === 'data') data.push(value)
  }
  if (data.length === 0 && id === null) return null
  const text = data.join('\n')
  let parsed: unknown = text
  try {
    parsed = text ? JSON.parse(text) : null
  } catch {
    // Служба шлёт JSON, но кадр-пульс или чужой прокси могут прислать что угодно.
    parsed = text
  }
  return { id, kind, data: parsed }
}

/**
 * Прочитать поток до конца, отдавая кадры по мере прихода.
 * Возвращает управление, когда служба закрыла поток или сработал `signal`.
 */
async function readStream(
  url: string,
  lastEventId: string | null,
  signal: AbortSignal,
  onFrame: (frame: SseFrame) => void,
  onOpen: () => void,
): Promise<void> {
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  if (lastEventId !== null) headers['Last-Event-ID'] = lastEventId

  const response = await fetch(url, { headers, credentials: 'include', signal })
  if (!response.ok || !response.body) {
    throw new Error(`поток ${url} ответил ${response.status}`)
  }
  onOpen()

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // Кадры разделены пустой строкой. `\r\n` терпим: его ставят прокси.
    const separator = /\r?\n\r?\n/
    let hit = separator.exec(buffer)
    while (hit) {
      const chunk = buffer.slice(0, hit.index).replace(/\r/g, '')
      buffer = buffer.slice(hit.index + hit[0].length)
      const frame = parseFrame(chunk)
      if (frame) onFrame(frame)
      hit = separator.exec(buffer)
    }
  }
}

export type SseOptions = {
  /** Адрес потока. `null` — не подключаться (например, нет ещё id задания). */
  url: string | null
  /** Что делать с каждым кадром. Вызывается и для кадров, пришедших после обрыва. */
  onFrame?: (frame: SseFrame) => void
  /** Вернуть `true` — поток закрывается насовсем и переподключений не будет. */
  stopOn?: (frame: SseFrame) => boolean
  /**
   * Спрашивается перед каждым переподключением — и после штатного закрытия
   * потока службой, и после обрыва. `false` закрывает подписку насовсем.
   *
   * Нужен потому, что «служба закрыла поток» само по себе ничего не значит:
   * поток задания закрывается на конце работы, а поток человека — по потолку
   * времени соединения, и его надо открыть заново. Отличить одно от другого
   * может только тот, кто знает, за чем следит.
   */
  shouldReconnect?: () => boolean | Promise<boolean>
  /** Сколько последних кадров держать в состоянии. 0 — не держать вовсе. */
  keep?: number
}

export type SseState = {
  frames: SseFrame[]
  status: SseStatus
  lastEventId: string | null
  /** Закрыть поток руками (например, кнопкой «отменить»). */
  close: () => void
}

/**
 * Подписка на поток службы.
 *
 * Кадры складываются в `frames` (последние `keep` штук) и заодно уезжают в
 * `onFrame` — второе нужно тем, кто обновляет кэш TanStack Query и не хочет
 * перерисовки на каждый кадр.
 */
export function useSseStream({
  url,
  onFrame,
  stopOn,
  shouldReconnect,
  keep = 200,
}: SseOptions): SseState {
  const [frames, setFrames] = useState<SseFrame[]>([])
  const [status, setStatus] = useState<SseStatus>('idle')
  const [lastEventId, setLastEventId] = useState<string | null>(null)

  // Колбэки живут в ref: иначе новая стрелка в родителе рвала бы поток на
  // каждой перерисовке — а это ровно то, от чего дочитывание и защищает.
  const onFrameRef = useRef(onFrame)
  const stopOnRef = useRef(stopOn)
  const shouldReconnectRef = useRef(shouldReconnect)
  onFrameRef.current = onFrame
  stopOnRef.current = stopOn
  shouldReconnectRef.current = shouldReconnect

  const abortRef = useRef<AbortController | null>(null)
  const stoppedRef = useRef(false)

  const close = useCallback(() => {
    stoppedRef.current = true
    abortRef.current?.abort()
    setStatus('closed')
  }, [])

  useEffect(() => {
    if (!url) {
      setStatus('idle')
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    stoppedRef.current = false
    let cursor: string | null = null
    let attempt = 0
    let cancelled = false

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, ms)
        controller.signal.addEventListener('abort', () => {
          clearTimeout(timer)
          resolve()
        })
      })

    const loop = async () => {
      while (!cancelled && !stoppedRef.current) {
        setStatus(attempt === 0 ? 'connecting' : 'reconnecting')
        try {
          await readStream(
            url,
            cursor,
            controller.signal,
            (frame) => {
              if (frame.id !== null) {
                cursor = frame.id
                setLastEventId(frame.id)
              }
              onFrameRef.current?.(frame)
              if (keep > 0) setFrames((was) => [...was, frame].slice(-keep))
              if (stopOnRef.current?.(frame)) {
                stoppedRef.current = true
                controller.abort()
              }
            },
            () => {
              attempt = 0
              setStatus('open')
            },
          )
          // Служба закрыла поток штатно. Для задания это конец работы; для
          // потока человека — истёкший потолок соединения, и тогда цикл
          // подключается заново, с того же курсора. Кто из двух — знает
          // `shouldReconnect`.
          if (stoppedRef.current || cancelled) break
        } catch {
          if (cancelled || controller.signal.aborted) break
          setStatus('error')
        }
        if (cancelled || stoppedRef.current) break
        if (shouldReconnectRef.current) {
          const again = await shouldReconnectRef.current()
          if (!again) {
            stoppedRef.current = true
            break
          }
        }
        if (cancelled) break
        await sleep(BACKOFF[Math.min(attempt, BACKOFF.length - 1)] ?? 10000)
        attempt += 1
      }
      if (!cancelled) setStatus(stoppedRef.current ? 'closed' : 'idle')
    }

    void loop()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [url, keep])

  return { frames, status, lastEventId, close }
}
