/**
 * AgentSection — «Агент и модели» (`/settings/agent`).
 *
 * Две настройки, и обе живут в профиле (`PATCH /api/auth/me`), а не в браузере:
 * поставщик по умолчанию и «переписывать ли агенту ручные правки». Хранение в
 * службе здесь не прихоть — человек открывает работу с ноутбука и с чужой
 * машины, и умолчание, оставшееся в `localStorage` первой, на второй молча
 * исчезает.
 *
 * **В списке — только поставщики моделей и только те, у кого есть ключ.**
 * Распознавание рукописи (`myscript_app`, `myscript_hmac`) в этот список не
 * попадает: пресета у него нет вовсе, и задание с таким `endpoint` служба
 * отвергает `400 unknown_provider` — то есть выбранный здесь MyScript был бы
 * агентом, который не работает. Поставщик без ключа не показывается по той же
 * причине: платить за прогон нечем, общего ключа службы нет.
 *
 * **«Ничего не выбрано» — законный ответ**, и он же умолчание: тогда берётся
 * ключ, заведённый первым (`features/reports/data.defaultProvider`). Правило
 * простое и предсказуемое: завёл один ключ — им и работает, не заходя сюда
 * вовсе.
 *
 * Модель поставщика выбирается не здесь, а строкой самого поставщика
 * (`ProvidersSection`): она свойство ключа, а не профиля, и стоять должна там,
 * где видно, к какому ключу относится.
 */
import { useState } from 'react'

import { useT } from '@/i18n'
import { errorText } from '@/api'
import { useMe, useUpdateProfile } from '@/api/hooks'
import { Card, Chip, Select, SkeletonLines, Switch } from '@/ui'

import { useKeyProviders } from './api'
import { modelProviders } from './types'

export function AgentSection() {
  const t = useT()
  const me = useMe()
  const providers = useKeyProviders()
  const save = useUpdateProfile()

  const все = modelProviders(providers.data)
  const с_ключом = все.filter((имя) => providers.data?.has_key?.[имя])

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
        {/* Пустой пункт — «первый заведённый ключ», а не «ничего не работает». */}
        <option value="">{t('settings.agent.presetAuto')}</option>
        {с_ключом.map((имя) => (
          <option key={имя} value={имя}>
            {имя}
            {providers.data?.model?.[имя] ? ` · ${providers.data.model[имя]}` : ''}
          </option>
        ))}
        {/* Выбранный прежде поставщик, у которого ключа уже нет, из списка не
            исчезает: иначе поле показывало бы пустоту там, где в профиле стоит
            имя, и человек чинил бы не то. Пометка рядом называет беду. */}
        {выбран && !с_ключом.includes(выбран) && (
          <option value={выбран}>{`${выбран} — ${t('settings.agent.noKey')}`}</option>
        )}
      </Select>

      {с_ключом.length === 0 && <Chip tone="warn">{t('settings.agent.nothing')}</Chip>}

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
