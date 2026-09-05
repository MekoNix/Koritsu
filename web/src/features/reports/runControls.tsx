/**
 * runControls — выбор пресета модели и цена прогона.
 *
 * **Цена и остаток показываются ДО нажатия**: оба числа
 * приезжают одним ответом `GET /api/usage` — цена вида задания и остаток месяца,
 * — и показываются рядом с кнопкой, а не после отказа по лимиту.
 *
 * **Пресет — это `payload.endpoint`.** Список берётся у службы вместе с тем,
 * чем по каждому платить (`own` | `shared` | `none`): пресет, которым платить
 * нечем, выбирать бессмысленно, и вместо молчаливого отказа человеку показана
 * ссылка в настройки.
 */
import { Link } from 'react-router-dom'

import type { Usage } from '@/api/types'
import { useT } from '@/i18n'

import type { ProvidersBody } from './types'

export function ModelPicker({
  providers,
  value,
  onChange,
  disabled,
}: {
  providers: ProvidersBody | undefined
  value: string | null
  onChange: (endpoint: string) => void
  disabled?: boolean
}) {
  const t = useT()
  const список = providers?.providers ?? []
  const источник = providers?.key_source ?? {}
  const платить_нечем = список.length > 0 && список.every((p) => источник[p] === 'none')

  if (платить_нечем || список.length === 0) {
    return (
      <span className="text-xs text-warn">
        {t('reports.model.noKeys')}{' '}
        <Link to="/settings" className="underline">
          {t('reports.model.toSettings')}
        </Link>
      </span>
    )
  }

  return (
    <label className="flex items-center gap-s2 text-xs text-muted">
      {t('reports.model.label')}
      <select
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-btn border border-line-strong bg-surface px-2 py-1 text-xs text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-45"
      >
        {список.map((p) => (
          <option key={p} value={p} disabled={источник[p] === 'none'}>
            {p}
            {источник[p] === 'shared' ? ` · ${t('reports.model.shared')}` : ''}
            {источник[p] === 'none' ? ` · ${t('reports.model.noKey')}` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}

/**
 * «Стоит столько, осталось столько». Цена берётся из того же ответа, что и
 * остаток, — они не могут разойтись, потому что приезжают вместе.
 */
export function PriceHint({ kind, usage }: { kind: string; usage: Usage | undefined }) {
  const t = useT()
  if (!usage) return null
  const цена = usage.prices?.[kind] ?? 0
  const мало = цена > usage.remaining_units
  return (
    <span className={мало ? 'text-err' : undefined}>
      {t('reports.price.line', {
        price: цена.toLocaleString('ru-RU'),
        left: usage.remaining_units.toLocaleString('ru-RU'),
      })}
      {мало ? ` · ${t('reports.price.notEnough')}` : ''}
    </span>
  )
}
