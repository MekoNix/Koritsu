/**
 * useUserEvents — единственный поток человека на всё приложение.
 *
 * Открывается один раз в оболочке (`app/AppShell`) и живёт, пока человек не
 * ушёл. Два кадра, которые шлёт служба (`packages/api/events/routes.py`):
 *
 * * `notification` — что-то, достойное колокольчика;
 * * `job_finished` — задание дошло до конечного состояния.
 *
 * Что делает хук: сбрасывает ключи кэша (`notifications`, `jobs`, `usage`) и
 * зовёт тост на завершение фоновой задачи. Тосты — только на завершение и на
 * ошибку, всё прочее оседает в колокольчике; поэтому
 * решение «тостить или нет» принимается ровно здесь, а не в каждом экране.
 *
 * **Тост на удачу — только на конец целого прогона.** Заполнение одного тега и
 * разбор одного принесённого файла тоже кончаются заданием, но человек в этот
 * момент смотрит ровно на то место, где результат и появляется: текст втекает в
 * поле тега, файл встаёт в опись. Тост поверх этого сообщал бы то, что уже
 * видно, — а на прогоне из двадцати тегов вырастал в двадцать всплывших
 * прямоугольников подряд. Отказ тостится по-прежнему на любом задании: беду,
 * в отличие от удачи, человек по экрану не прочитает.
 *
 * **Тост на упавшее задание — один на всё приложение, и он здесь.** Раньше
 * области тостили провал ещё и сами (отчёты, схемы), и человек получал два
 * тоста на одну беду. Причину показывает оболочка: `data.code` уведомления
 * (`notifications/service.py`) — это тот же код отказа, что и везде, и русский
 * текст ему даёт `errors.json`. Свои тосты области оставляют только на отказ
 * обычного запроса (не задания): его никто, кроме области, не увидит.
 *
 * Курсор потока — время ISO, служба продолжает с него по `Last-Event-ID`;
 * переподключение бесконечное, потому что поток человека закрывается по
 * потолку времени соединения, а не по концу работы.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'

import { t as translate, useT } from '@/i18n'
import { withBase } from '@/lib/basePath'
import { useToast } from '@/ui/toast'

import { keys } from '../queryKeys'
import { useSseStream, type SseFrame, type SseState } from '../sse'
import type { Notification } from '../types'

/** Виды уведомлений, на которые положен тост (`notifications/models.py`). */
const JOB_DONE = 'job_done'
const JOB_FAILED = 'job_failed'
const JOB_CANCELLED = 'job_cancelled'
const LIMIT_EXHAUSTED = 'limit_exhausted'

/**
 * Виды заданий, чей удачный конец человек и так видит на экране, — им тоста не
 * положено (см. докстроку модуля): `fill_tag` печатает текст прямо в поле тега,
 * `parse` ставит разобранный файл в опись работы. Список маленький намеренно:
 * тост — это про «сделано то, чего ты не видишь», и незнакомый вид задания
 * честнее протостить, чем промолчать.
 */
const БЕЗ_ТОСТА = new Set(['fill_tag', 'parse'])

/** Вид задания из уведомления: по нему решается, тостить ли удачу. */
function видЗадания(card: Notification | null): string {
  const вид = card?.data?.job_kind
  return typeof вид === 'string' ? вид : ''
}

/**
 * Почему задание упало — строкой для человека.
 *
 * Код лежит в `data.code` уведомления. Русский текст ему даёт общий словарь
 * отказов; кода нет или он незнаком — второй строки у тоста просто не будет:
 * английское `unknown` в тосте хуже, чем его отсутствие.
 */
function failedReason(card: Notification | null): string | undefined {
  const code = card?.data?.code
  if (typeof code !== 'string' || !code) return undefined
  const key = `errors.${code}`
  const text = translate(key)
  return text === key ? undefined : text
}

export function useUserEvents(enabled = true): SseState {
  const qc = useQueryClient()
  const toast = useToast()
  const t = useT()

  const onFrame = useCallback(
    (frame: SseFrame) => {
      void qc.invalidateQueries({ queryKey: keys.notifications })
      void qc.invalidateQueries({ queryKey: keys.jobs.all })

      const card = frame.data as Notification | null
      const kind = card?.kind ?? frame.kind

      if (kind === JOB_DONE || kind === JOB_FAILED || kind === JOB_CANCELLED) {
        // Остаток месяца изменился вместе с концом задания.
        void qc.invalidateQueries({ queryKey: keys.usage })
      }

      // Тост — только на завершение фоновой задачи и на беду. Остальное человек
      // найдёт в колокольчике: это и есть правило о тостах.
      if (kind === JOB_DONE && !БЕЗ_ТОСТА.has(видЗадания(card)))
        toast.success(t('notifications.jobDone'))
      else if (kind === JOB_FAILED) toast.error(t('notifications.jobFailed'), failedReason(card))
      else if (kind === LIMIT_EXHAUSTED) toast.error(t('errors.limit_exhausted'))
    },
    [qc, toast, t],
  )

  // Поток человека переподключается всегда: его закрывает потолок времени
  // соединения, а не конец работы.
  const shouldReconnect = useCallback(() => true, [])

  return useSseStream({
    // `withBase` — префикс пути сайта: поток идёт своим `fetch`'ем, мимо
    // клиента API, который ставит префикс сам.
    url: enabled ? withBase('/api/events') : null,
    onFrame,
    shouldReconnect,
    // Кадры складывать незачем: всё нужное уже разложено по кэшу и колокольчику.
    keep: 0,
  })
}
