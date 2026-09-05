/**
 * AgentSection — «Агент и модели» (`/settings/agent`).
 *
 * Две настройки, и обе живут в профиле (`PATCH /api/auth/me`), а не в браузере:
 * пресет по умолчанию и «переписывать ли агенту ручные правки». Хранение в
 * службе здесь не прихоть — человек открывает работу с ноутбука и с чужой
 * машины, и умолчание, оставшееся в `localStorage` первой, на второй молча
 * исчезает.
 *
 * **Пресет показывается вместе с тем, чем за него платят** (`key_source` из
 * `GET /api/keys/providers`): `own` — свой ключ, `shared` — общий ключ службы,
 * `none` — платить нечем. Выбрать пресет, которым платить нечем, служба
 * позволит (ключ может появиться завтра), но экран обязан сказать это словами
 * до нажатия, а не отказом после.
 *
 * **«Ничего не выбрано» — законный ответ**, и он же умолчание: тогда пресет
 * подставляет правило сайта — сначала свой ключ, потом общий
 * (`features/reports/data.defaultProvider`). Поэтому в списке есть пустой
 * пункт, а не только пресеты.
 */
import { useState } from 'react'

import { useT } from '@/i18n'
import { errorText } from '@/api'
import { useMe, useUpdateProfile } from '@/api/hooks'
import { Card, Chip, Select, SkeletonLines, Switch } from '@/ui'

import { useKeyProviders } from './api'
import type { KeySource } from './types'

const ТОН: Record<KeySource, 'ok' | 'accent' | 'warn'> = {
  own: 'ok',
  shared: 'accent',
  none: 'warn',
}

export function AgentSection() {
  const t = useT()
  const me = useMe()
  const providers = useKeyProviders()
  const save = useUpdateProfile()

  const имена = providers.data?.providers ?? []
  const источник = providers.data?.key_source

  // Что человек только что выбрал, пока правка едет в службу. Без этого поле
  // на мгновение возвращается к прежнему значению — профиль обновится только
  // ответом, — и выглядит это как «не сохранилось».
  const [свежий_пресет, setСвежийПресет] = useState<string | null>(null)
  const [свежее_переписывание, setСвежееПереписывание] = useState<boolean | null>(null)
  const выбран = свежий_пресет ?? me.data?.default_endpoint ?? ''
  const переписывать = свежее_переписывание ?? me.data?.agent_overwrite ?? false

  const сохранить_пресет = (значение: string) => {
    setСвежийПресет(значение)
    save.mutate({ default_endpoint: значение }, { onSettled: () => setСвежийПресет(null) })
  }

  const сохранить_переписывание = (значение: boolean) => {
    setСвежееПереписывание(значение)
    save.mutate({ agent_overwrite: значение }, { onSettled: () => setСвежееПереписывание(null) })
  }

  return (
    <Card title={t('settings.agent.title')} desc={t('settings.agent.text')}>
      {me.isLoading && <SkeletonLines count={2} />}

      <Select
        label={t('settings.agent.preset')}
        hint={t('settings.agent.presetHint')}
        value={выбран}
        disabled={providers.isLoading}
        onChange={(event) => сохранить_пресет(event.target.value)}
      >
        {/* Пустой пункт — это «решает сайт», а не «ничего не работает». */}
        <option value="">{t('settings.agent.presetAuto')}</option>
        {имена.map((имя) => (
          <option key={имя} value={имя}>
            {имя}
          </option>
        ))}
      </Select>

      {имена.length > 0 && (
        <ul className="flex flex-wrap gap-s2">
          {имена.map((имя) => {
            const состояние = источник?.[имя]
            return (
              <li key={имя} className="flex items-center gap-1.5">
                <span className="font-mono text-xs text-muted">{имя}</span>
                <Chip tone={состояние ? ТОН[состояние] : 'muted'}>
                  {t(`settings.keys.source.${состояние ?? 'unknown'}`)}
                </Chip>
              </li>
            )
          })}
        </ul>
      )}

      <label className="flex items-start gap-s3">
        <Switch
          checked={переписывать}
          disabled={me.isLoading}
          onChange={(event) => сохранить_переписывание(event.target.checked)}
        />
        <span className="flex flex-col gap-0.5">
          <span className="text-sm font-medium text-ink-strong">
            {t('settings.agent.overwrite')}
          </span>
          <span className="text-xs text-muted">{t('settings.agent.overwriteHint')}</span>
        </span>
      </label>

      {save.isError && <p className="text-sm text-err">{errorText(save.error)}</p>}
    </Card>
  )
}
