/**
 * runControls — выбор пресета модели.
 *
 * **Цены и остатка рядом с кнопками нет.** Цена прогона динамическая: она
 * зависит от того, сколько модель прочтёт и напишет, и названное до нажатия
 * число было бы обещанием, которого никто не давал. Расход и потолок месяца
 * человек смотрит одним местом — «Расход и лимиты» в настройках.
 *
 * **Пресет — это `payload.endpoint`.** Список берётся у службы вместе с тем,
 * есть ли по каждому ключ (`has_key`): поставщик без ключа не работает вовсе —
 * общего ключа службы нет, — и вместо молчаливого отказа человеку показана
 * ссылка в настройки.
 *
 * **Распознавание рукописи в список не попадает.** Оно живёт в том же ответе
 * службы (`kind: "ink"`), но пресета у него нет, и выбранный здесь `myscript_app`
 * был бы прогоном, который служба отвергает `400 unknown_provider`.
 */
import { Link } from 'react-router-dom'

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
  const список = (providers?.providers ?? []).filter(
    (p) => (providers?.kind?.[p] ?? 'model') === 'model',
  )
  const есть_ключ = providers?.has_key ?? {}
  const модель = providers?.model ?? {}
  const платить_нечем = список.length > 0 && список.every((p) => !есть_ключ[p])

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
          <option key={p} value={p} disabled={!есть_ключ[p]}>
            {p}
            {модель[p] ? ` · ${модель[p]}` : ''}
            {!есть_ключ[p] ? ` · ${t('reports.model.noKey')}` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}
