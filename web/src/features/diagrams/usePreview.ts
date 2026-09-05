/**
 * usePreview — построение схемы: когда его просить и как не попасть в 429.
 *
 * **Схема сама по правке кода не перестраивается.** Раньше перестраивалась — и
 * это оказалось худшим, что есть на экране: человек правит одну строку, а
 * картинка справа скачет, теряя место, на которое он смотрел; каждое нажатие
 * клавиши при этом стоит подпроцесса с tree-sitter'ом на службе. Осталась ровно
 * одна самостоятельная постройка — **первая**: экран, открытый с пустым полем,
 * обязан показать схему, как только код в нём появился, иначе человек не узнает,
 * что кнопка вообще что-то делает. Дальше — только по кнопке.
 *
 * Что здесь и происходит:
 *
 * 1. **Одна автоматическая постройка.** Пока схемы ещё не было, первая правка
 *    кода после задержки строит её сама; больше самостоятельных построек на
 *    этом экране не будет.
 * 2. **Задержка после правки** (`ЗАДЕРЖКА_МС`): пока человек печатает, запроса
 *    нет вовсе — даже той единственной первой постройки.
 * 3. **Пауза между запросами** (`ПАУЗА_МС`): две быстрые постройки подряд не
 *    дают больше одного запроса за это время.
 * 4. **429 гасит всё**: после отказа по темпу схема не строится сама и подавно,
 *    экран пишет спокойную строку, а человек нажимает кнопку, когда захочет.
 *    Тоста при этом нет — тост на каждую секунду молчаливого счётчика и есть та
 *    самая ошибка, которой просили не делать.
 *
 * Отказ построения живёт рядом со схемой (`error`), а не всплывает тостом: беда
 * здесь — свойство кода в левой половине экрана, и показывать её надо там, куда
 * человек смотрит.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { isApiError } from '@/api'

import type { Notice, PreviewOut } from './types'

/** Сколько молчим после последней правки кода перед первой постройкой. */
export const ЗАДЕРЖКА_МС = 1200

/** Сколько минимум проходит между двумя запросами построения. */
export const ПАУЗА_МС = 2500

/** Код отказа службы по темпу (`api/modules/diagrams.py`). */
export const RATE_LIMITED = 'rate_limited'

export type PreviewState = {
  /** XML схемы: от службы или поправленный руками в редакторе. */
  xml: string | null
  notices: Notice[]
  error: unknown
  /** Запрос в пути. */
  pending: boolean
  /** Код есть, схемы ещё нет — ждём задержки перед первой постройкой. */
  waiting: boolean
  /** Служба отказала по темпу. */
  rateLimited: boolean
  /** Есть ли неучтённые правки: код правили после того, как схема построена. */
  stale: boolean
  /** Построить сейчас (кнопка, Ctrl+Enter). */
  run: () => void
  /** Схему поправили руками в draw.io — держим её как текущую. */
  setXml: (xml: string) => void
  /** Показать готовую схему (открытую из списка) и считать её построенной. */
  showBuilt: (xml: string, notices?: Notice[]) => void
}

export type PreviewOptions = {
  /**
   * Отпечаток входа: код, язык, режим. Строкой, а не объектом: сравнивать надо
   * по значению, а зависимость эффекта сравнивается по ссылке.
   */
  signature: string
  /** Есть ли что строить (пустой код в службу не отправляем). */
  enabled: boolean
  request: () => Promise<PreviewOut>
}

export function usePreview({ signature, enabled, request }: PreviewOptions): PreviewState {
  const [xml, setXmlState] = useState<string | null>(null)
  const [notices, setNotices] = useState<Notice[]>([])
  const [error, setError] = useState<unknown>(null)
  const [pending, setPending] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [rateLimited, setRateLimited] = useState(false)
  /** Отпечаток, который уже показан. Он же ответ на вопрос «код правили?». */
  const [показан, setПоказан] = useState<string | null>(null)

  const запрос = useRef(request)
  запрос.current = request
  /** Когда сходили в службу в прошлый раз — чтобы держать паузу. */
  const прошлый = useRef(0)
  /** Номер запроса: ответ на устаревший запрос не должен перебивать свежий. */
  const счётчик = useRef(0)
  /** Была ли уже хоть одна постройка на этом экране. */
  const строили = useRef(false)
  /** Схему только что показали готовой: отпечаток кода надо счесть учтённым. */
  const принять = useRef(false)

  const выполнить = useCallback(async () => {
    const мой = ++счётчик.current
    прошлый.current = Date.now()
    строили.current = true
    setПоказан(signature)
    setPending(true)
    setWaiting(false)
    try {
      const ответ = await запрос.current()
      if (счётчик.current !== мой) return
      setXmlState(ответ.xml)
      setNotices(ответ.notices ?? [])
      setError(null)
      setRateLimited(false)
    } catch (беда) {
      if (счётчик.current !== мой) return
      setError(беда)
      if (isApiError(беда) && беда.code === RATE_LIMITED) {
        // Отказ по темпу — не беда кода: схема, что была, остаётся на месте.
        setRateLimited(true)
      }
    } finally {
      if (счётчик.current === мой) setPending(false)
    }
  }, [signature])

  const run = useCallback(() => {
    if (!enabled) return
    setRateLimited(false)
    void выполнить()
  }, [enabled, выполнить])

  const showBuilt = useCallback((значение: string, замечания?: Notice[]) => {
    строили.current = true
    setXmlState(значение)
    setNotices(замечания ?? [])
    setError(null)
    // Отпечаток кода станет известен на следующем проходе: код схемы приезжает
    // тем же ответом и попадает в состояние экрана рядом с этим вызовом.
    принять.current = true
  }, [])

  // Отпечаток кода той схемы, которую показали готовой. Зависит и от `xml`, а
  // не от одного отпечатка: открытая из списка схема бывает построена ровно из
  // того кода, что уже лежит в поле, — тогда отпечаток не меняется, а картинка
  // меняется всегда.
  useEffect(() => {
    if (!принять.current) return
    принять.current = false
    setПоказан(signature)
  }, [signature, xml])

  // Единственная самостоятельная постройка — первая: код появился, схемы ещё
  // не было. Дальше правка кода ничего не запускает: `строили` уже поднят.
  useEffect(() => {
    if (!enabled || строили.current) {
      setWaiting(false)
      return
    }
    setWaiting(true)
    const пауза = Math.max(0, ПАУЗА_МС - (Date.now() - прошлый.current))
    const срок = window.setTimeout(() => void выполнить(), ЗАДЕРЖКА_МС + пауза)
    return () => window.clearTimeout(срок)
  }, [signature, enabled, выполнить])

  const setXml = useCallback((значение: string) => setXmlState(значение), [])

  return {
    xml,
    notices,
    error,
    pending,
    waiting,
    rateLimited,
    stale: !!xml && !принять.current && показан !== signature,
    run,
    setXml,
    showBuilt,
  }
}
