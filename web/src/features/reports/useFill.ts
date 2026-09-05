/**
 * useFill — прогон модели по тегам: постановка задания, поток текста, конец.
 *
 * Одно место на оба прогона — тег (`fill_tag`) и весь отчёт (`fill_report`), —
 * потому что снаружи они различаются только списком ключей, а внутри у них один
 * и тот же поток: куски `text`, потом `tag_closed` на каждый закрытый тег.
 *
 *     Как текст попадает в нужный тег
 *     -------------------------------
 *
 * Служба не подписывает куски текста ключом тега (`common.Прогон.текст` пишет
 * только сам кусок), и подписать их она не может: модель отвечает потоком
 * задолго до того, как станет ясно, что именно она дописала. Зато порядок
 * известен точно: куски идут подряд, а `tag_closed` называет тег, к которому
 * они относились. Отсюда правило разбора:
 *
 *   * куски копятся в буфере;
 *   * `tag_closed` кладёт буфер на названный тег и очищает его;
 *   * тег, который печатается прямо сейчас, — следующий по списку задания.
 *
 * Список задания мы знаем сами: `fill_tag` — один ключ, `fill_report` — те, что
 * мы же и послали в `payload.keys`. Угадывания здесь нет, есть договор.
 *
 * **Разбор — чистая свёртка по кадрам, а не накопление в `ref`.** Поток
 * переподключается с последнего события (`Last-Event-ID`), после чего кадры
 * приезжают те же самые; накопитель, переживший переподключение, удвоил бы
 * текст, а свёртка по полному списку кадров даёт один и тот же ответ сколько
 * угодно раз.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { errorText, keys } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useT } from '@/i18n'
import { useToast } from '@/ui'
import { useEnqueueJob } from '@/features/projects/data'

import { EV_TAG_CLOSED, EV_TEXT, FILL_REPORT, FILL_TAG } from './types'

/** Задание, которое сейчас идёт, вместе с тем, по каким тегам оно идёт. */
type Running = { id: string; kind: string; keys: string[] }

export type FillState = {
  /** Идёт ли прогон прямо сейчас. */
  running: boolean
  /** Вид идущего задания или `null`. */
  kind: string | null
  /** Ключи, поле которых на время прогона заблокировано (решение владельца). */
  busy: Set<string>
  /** Тег, который печатается прямо сейчас. */
  current: string | null
  /** Текст, пришедший по потоку для этого тега; `undefined` — ничего не пришло. */
  textFor: (key: string) => string | undefined
  /** Сколько тегов уже закрыто этим прогоном. */
  closed: number
  /** Всего тегов в прогоне. */
  total: number
  /** Прогон одного тега. */
  fillTag: (key: string) => void
  /** Прогон по списку тегов; пустой список — по всем незаполненным. */
  fillReport: (keys: string[]) => void
  /** Отказ постановки задания (лимит, нет ключа) — показывается на экране. */
  startError: unknown
}

export function useFill(projectId: string, endpoint: string | null): FillState {
  const t = useT()
  const toast = useToast()
  const qc = useQueryClient()
  const enqueue = useEnqueueJob()

  const [running, setRunning] = useState<Running | null>(null)
  const stream = useJobStream(running?.id)
  // Чтобы не показать конец одного задания дважды: поток закрывается, карточка
  // перечитывается, и `done` становится истиной не один раз.
  const закрыто = useRef<string | null>(null)

  const разбор = useMemo(() => {
    const готовые: Record<string, string> = {}
    let буфер = ''
    let индекс = 0
    for (const событие of stream.events) {
      const тело = (событие.data ?? {}) as { text?: unknown; key?: unknown }
      if (событие.kind === EV_TEXT) {
        буфер += typeof тело.text === 'string' ? тело.text : ''
      } else if (событие.kind === EV_TAG_CLOSED) {
        const ключ = typeof тело.key === 'string' ? тело.key : (running?.keys[индекс] ?? '')
        if (ключ) готовые[ключ] = буфер
        буфер = ''
        индекс += 1
      }
    }
    return { готовые, буфер, индекс }
  }, [stream.events, running])

  const идёт = !!running && !stream.done
  const current = идёт ? (running?.keys[разбор.индекс] ?? null) : null

  // Конец задания: перечитать теги и значения, сказать словами, чем кончилось.
  useEffect(() => {
    if (!running || !stream.done || закрыто.current === running.id) return
    закрыто.current = running.id
    void qc.invalidateQueries({ queryKey: keys.reports.tags(projectId) })
    void qc.invalidateQueries({ queryKey: keys.reports.values(projectId) })
    void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    for (const ключ of running.keys) {
      void qc.invalidateQueries({ queryKey: keys.reports.versions(projectId, ключ) })
    }
    // Тоста на упавшее задание здесь нет: его показывает оболочка
    // (`useUserEvents`) по коду из уведомления, и второй был бы дублем —
    // решение сведения ночи 1.
    setRunning(null)
  }, [running, stream.done, stream.job, projectId, qc])

  const поставить = useCallback(
    (kind: string, ключи: string[]) => {
      if (!endpoint) return
      enqueue.mutate(
        {
          kind,
          projectId,
          payload:
            kind === FILL_TAG
              ? { key: ключи[0], endpoint, overwrite: true }
              : { endpoint, keys: ключи, overwrite: false },
        },
        {
          onSuccess: (задание) => {
            закрыто.current = null
            setRunning({ id: задание.id, kind, keys: ключи })
          },
          onError: (беда) => toast.error(t('reports.toast.fillFailed'), errorText(беда)),
        },
      )
    },
    [enqueue, endpoint, projectId, toast, t],
  )

  const fillTag = useCallback((key: string) => поставить(FILL_TAG, [key]), [поставить])
  const fillReport = useCallback((ключи: string[]) => поставить(FILL_REPORT, ключи), [поставить])

  const textFor = useCallback(
    (key: string) => {
      if (key === current) return разбор.буфер
      return разбор.готовые[key]
    },
    [current, разбор],
  )

  return {
    running: идёт,
    kind: идёт ? (running?.kind ?? null) : null,
    busy: new Set(идёт ? (running?.keys ?? []) : []),
    current,
    textFor,
    closed: разбор.индекс,
    total: running?.keys.length ?? 0,
    fillTag,
    fillReport,
    startError: enqueue.error,
  }
}
