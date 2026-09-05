/**
 * ClockWidget — часы. Маленькая плитка, как в макете.
 *
 * Часовой пояс берётся у браузера (`Intl`), а не из настроек: поля часового
 * пояса у службы пока нет, а показывать «Москва» всем подряд — врать. Появится
 * поле в профиле — здесь поменяется одна строка.
 *
 * Тик раз в секунду и `setTimeout` до следующей секунды, а не `setInterval` в
 * 1000 мс: интервал уплывает, и минута меняется на глазах не тогда, когда
 * меняется на самом деле.
 */
import { useEffect, useState } from 'react'

import { useT } from '@/i18n'

import { Widget } from './Widget'

function timezoneLabel(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
    // «Europe/Moscow» → «Moscow»: имя области человеку ничего не добавляет.
    return zone ? zone.slice(zone.lastIndexOf('/') + 1).replace(/_/g, ' ') : ''
  } catch {
    return ''
  }
}

export function ClockWidget() {
  const t = useT()
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const timer = setTimeout(() => setNow(new Date()), 1000 - (Date.now() % 1000))
    return () => clearTimeout(timer)
  }, [now])

  const zone = timezoneLabel()

  return (
    <Widget>
      <div className="flex h-full flex-col justify-between gap-s2">
        <span className="text-xs uppercase tracking-wider text-muted">
          {zone || t('dashboard.clock.local')}
        </span>
        <time
          dateTime={now.toISOString()}
          className="font-display text-2xl font-bold tabular-nums tracking-tight text-ink-strong"
        >
          {now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
        </time>
        <span className="text-xs text-muted">
          {now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })}
        </span>
      </div>
    </Widget>
  )
}
