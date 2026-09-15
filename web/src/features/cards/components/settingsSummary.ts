/**
 * settingsSummary — настройки захода одной строкой: «Вопросов: 20 · По темам, внутри случайно».
 *
 * Отдельным файлом, а не рядом с `Settings`: сводку показывают и строка настроек на
 * телефоне, и подсказка быстрого старта на странице набора.
 */
import type { useT } from '@/i18n'

import { SESSION_ALL, type CardSettings } from '../types'

type Перевод = ReturnType<typeof useT>

export function settingsSummary(t: Перевод, s: CardSettings): string {
  const части = [
    s.session_size === SESSION_ALL ? t('cards.settings.summaryAll') : t('cards.settings.summarySize', { n: s.session_size }),
    t(`cards.settings.orders.${s.order}.title`),
  ]
  if (s.include !== 'all') части.push(t(`cards.settings.includes.${s.include}.title`))
  if (s.topics !== null) части.push(t('cards.settings.summaryTopics', { n: s.topics.length }))
  return части.join(' · ')
}
