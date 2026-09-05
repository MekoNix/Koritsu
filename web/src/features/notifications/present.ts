/**
 * present — как уведомление выглядит: иконка, ключ заголовка, отметка времени.
 *
 * Отдельным файлом от разметки затем, что списков уведомлений два —
 * колокольчик в шапке и виджет дашборда, — а решение «job_failed показывается
 * красным восклицательным знаком и называется „Задание не выполнено“» одно.
 * Разметку они рисуют разную (пункт меню и строка карточки), общее — здесь.
 */
import { t } from '@/i18n'
import type { IconName } from '@/ui'

/** Вид уведомления → иконка и цвет. Неизвестный вид — нейтральная иконка. */
export const LOOK: Record<string, { icon: IconName; color: string }> = {
  job_done: { icon: 'checkCircle', color: 'text-ok' },
  job_failed: { icon: 'error', color: 'text-err' },
  job_cancelled: { icon: 'close', color: 'text-muted' },
  limit_exhausted: { icon: 'warning', color: 'text-warn' },
}

export function lookOf(kind: string): { icon: IconName; color: string } {
  return LOOK[kind] ?? { icon: 'info', color: 'text-muted' }
}

/**
 * Вид уведомления → ключ перевода заголовка. Служба присылает вид и данные, а
 * не готовый текст (тексты наружу по-английски), и русский текст собирается
 * здесь — по тому же словарю, что и тосты.
 */
export const TITLE_KEY: Record<string, string> = {
  job_done: 'notifications.jobDone',
  job_failed: 'notifications.jobFailed',
  job_cancelled: 'notifications.jobCancelled',
  limit_exhausted: 'notifications.limitExhausted',
}

/**
 * Вид задания → русское название («export» → «Выгрузка»).
 *
 * Словарь один на всех, кто показывает виды заданий: колокольчик, виджет
 * уведомлений на дашборде и очередь фоновых задач в шапке
 * (`app/shell/JobsMenu.tsx`). Два словаря видов разъехались бы в первый же
 * день, когда у службы появится новый вид.
 *
 * Незнакомый вид отдаётся как есть, а не ключом перевода: `probe` в шапке —
 * плохо, `notifications.kind.probe` — хуже.
 */
export function kindTitle(kind: string): string {
  if (!kind) return ''
  const текст = t(`notifications.kind.${kind}`)
  return текст === `notifications.kind.${kind}` ? kind : текст
}

/** Короткая отметка времени. Дата целиком нужна редко, минуты — всегда. */
export function when(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  return at.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
