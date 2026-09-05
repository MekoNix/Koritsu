/**
 * usePreview — предпросмотр схемы: когда его просить и как не попасть в 429.
 *
 * Предпросмотр — единственный тяжёлый маршрут службы, который дёргается прямо
 * из редактора: каждое нажатие клавиши могло бы стоить подпроцесса с
 * tree-sitter'ом. Служба поэтому считает темп (`KORITSU_PREVIEW_PER_MINUTE`,
 * тридцать в минуту на человека) и отвечает `429 rate_limited`. Сайт обязан не
 * доводить до этого числа сам, а доведя — не превращать отказ в ленту тостов.
 *
 * Три вещи, которые здесь и происходят:
 *
 * 1. **Задержка после правки** (`ЗАДЕРЖКА_МС`): пока человек печатает, запроса
 *    нет вовсе.
 * 2. **Пауза между запросами** (`ПАУЗА_МС`): даже быстрые правки не дают
 *    больше одного запроса за это время — тридцать в минуту это ровно две
 *    секунды на запрос, и берём с запасом.
 * 3. **429 гасит автообновление**: после отказа по темпу схема сама не
 *    строится, экран пишет спокойную строку, а человек нажимает «Построить
 *    схему», когда захочет. Тоста при этом нет — тост на каждую секунду
 *    молчаливого счётчика и есть та самая ошибка, которой просили не делать.
 *
 * Отказ предпросмотра живёт в самом предпросмотре (`error`), а не всплывает
 * тостом: беда здесь — свойство кода в левой половине экрана, и показывать её
 * надо там, куда человек смотрит.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { isApiError } from '@/api'

import type { Notice, PreviewOut } from './types'

/** Сколько молчим после последней правки кода. */
export const ЗАДЕРЖКА_МС = 1200

/** Сколько минимум проходит между двумя запросами предпросмотра. */
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
  /** Правки есть, ждём задержки или паузы. */
  waiting: boolean
  /** Служба отказала по темпу; автообновление выключено до нажатия кнопки. */
  rateLimited: boolean
  auto: boolean
  setAuto: (value: boolean) => void
  /** Построить сейчас, не дожидаясь задержки (кнопка, Ctrl+Enter). */
  run: () => void
  /** Схему поправили руками в draw.io — держим её как текущую. */
  setXml: (xml: string) => void
}

export type PreviewOptions = {
  /**
   * Отпечаток входа: код, язык, режим. Меняется — схему надо перестроить.
   * Строкой, а не объектом: сравнивать надо по значению, а зависимость эффекта
   * сравнивается по ссылке.
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
  const [auto, setAuto] = useState(true)

  const запрос = useRef(request)
  запрос.current = request
  /** Когда сходили в службу в прошлый раз — чтобы держать паузу. */
  const прошлый = useRef(0)
  /** Номер запроса: ответ на устаревший запрос не должен перебивать свежий. */
  const счётчик = useRef(0)
  /** Отпечаток, который уже показан: по нему видно, есть ли неучтённые правки. */
  const показан = useRef<string | null>(null)

  const выполнить = useCallback(async () => {
    const мой = ++счётчик.current
    прошлый.current = Date.now()
    показан.current = signature
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
        // Отказ по темпу — не беда кода: схема, что была, остаётся на месте,
        // а сами мы перестаём стучаться, пока человек не попросит.
        setRateLimited(true)
        setAuto(false)
      }
    } finally {
      if (счётчик.current === мой) setPending(false)
    }
  }, [signature])

  const run = useCallback(() => {
    if (!enabled) return
    // Нажатие кнопки — это и просьба построить сейчас, и просьба снова
    // обновлять на лету: выключилось автообновление само, а включать его
    // отдельным тумблером значило бы требовать двух действий вместо одного.
    setRateLimited(false)
    setAuto(true)
    void выполнить()
  }, [enabled, выполнить])

  // Само обновление: задержка после правки плюс пауза между запросами.
  useEffect(() => {
    if (!enabled || !auto) {
      setWaiting(false)
      return
    }
    if (показан.current === signature) return
    setWaiting(true)
    const пауза = Math.max(0, ПАУЗА_МС - (Date.now() - прошлый.current))
    const срок = window.setTimeout(() => void выполнить(), ЗАДЕРЖКА_МС + пауза)
    return () => window.clearTimeout(срок)
  }, [signature, enabled, auto, выполнить])

  const setXml = useCallback((значение: string) => setXmlState(значение), [])

  return {
    xml,
    notices,
    error,
    pending,
    waiting,
    rateLimited,
    auto,
    setAuto,
    run,
    setXml,
  }
}
