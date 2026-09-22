/**
 * ProvidersSection — «Поставщики моделей»: ключ и модель одной строкой.
 *
 * Раньше это были два списка на одном экране: ключи отдельно, выбор пресета
 * отдельно, — и человек читал их как два разных набора поставщиков. Вопросов у
 * него при этом три, и все про одного поставщика: заведён ли ключ, какой
 * моделью он работает и как это поменять. Поэтому строка одна на поставщика, и
 * в ней стоят все три ответа.
 *
 * **Ключ — условие, а не подробность.** Общего ключа службы больше нет: прогон
 * идёт на ключе самого человека, и поставщик без ключа не работает вовсе.
 * Отсюда две картины строки, а не оттенки одной: есть ключ — видно его хвост,
 * дату и выбор модели; нет ключа — видно поле ввода и больше ничего, потому что
 * выбирать модель нечем.
 *
 * **Модель спрашивается у поставщика.** Список приходит из
 * `GET /api/keys/{provider}/models`, то есть от него самого и по ключу этого же
 * человека. Не ответил — под полем честно стоит, почему, и остаётся имя из
 * пресета: выдуманные имена человек выбрал бы и получил отказ на прогоне.
 * Выбирается модель полем с поиском (`ModelCombobox`), а не родным списком:
 * у OpenRouter имён сотни, и пролистать их глазами нельзя.
 *
 * Служба никогда не возвращает ключ и не может: наружу уезжают поставщик,
 * четыре последних знака, выбранная модель и даты
 * (`keys/models.py: ModelKey.to_dict`). Поэтому здесь нет ни «показать», ни
 * «изменить» — только завести заново и отозвать.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import {
  Button,
  Card,
  Chip,
  Dialog,
  ErrorState,
  Icon,
  Input,
  Row,
  SkeletonLines,
  useToast,
} from '@/ui'

import {
  useAddModelKey,
  useKeyProviders,
  useModelKeys,
  useProviderModels,
  useRefreshProviderModels,
  useRevokeModelKey,
  useSetProviderModel,
} from './api'
import { formatDate } from './format'
import { ModelCombobox } from './ModelCombobox'
import { modelProviders, type ModelKey } from './types'

export function ProvidersSection() {
  const t = useT()
  const поставщики = useKeyProviders()
  const список = useModelKeys()
  const [отзываем, setОтзываем] = useState<ModelKey | null>(null)
  const отозвать = useRevokeModelKey()
  const toast = useToast()

  const имена = modelProviders(поставщики.data)
  const ключи = new Map((список.data ?? []).map((к) => [к.provider, к]))

  return (
    <>
      <Card title={t('settings.providers.title')} desc={t('settings.providers.text')}>
        {(поставщики.isLoading || список.isLoading) && <SkeletonLines count={3} />}
        {поставщики.isError && <ErrorState error={поставщики.error} />}

        {имена.length > 0 && (
          <ul className="flex flex-col gap-s3">
            {имена.map((имя) => (
              <li key={имя}>
                <ProviderRow
                  provider={имя}
                  ключ={ключи.get(имя) ?? null}
                  модель={поставщики.data?.model?.[имя] ?? ''}
                  onRevoke={() => setОтзываем(ключи.get(имя) ?? null)}
                />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Dialog
        open={отзываем !== null}
        onOpenChange={(открыто) => !открыто && setОтзываем(null)}
        title={t('settings.keys.revokeTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setОтзываем(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={отозвать.isPending}
              onClick={() => {
                if (!отзываем) return
                отозвать.mutate(отзываем.id, {
                  onSuccess: () => setОтзываем(null),
                  onError: (е) => toast.fail(е),
                })
              }}
            >
              {t('settings.keys.revoke')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">{t('settings.providers.revokeText')}</p>
        {отзываем && (
          <div className="mt-s3">
            <Row label={t('settings.keys.last4')}>
              <Chip tone="muted">…{отзываем.last4}</Chip>
            </Row>
          </div>
        )}
      </Dialog>
    </>
  )
}

/**
 * Одна строка списка: поставщик, его ключ и его модель.
 *
 * Своим компонентом, а не куском разметки в цикле: у строки своё состояние
 * (набранный ключ, открыта ли смена) и свой запрос моделей, и держать их
 * словарями по имени поставщика в родителе значило бы писать руками то, что
 * React делает сам.
 */
function ProviderRow({
  provider,
  ключ,
  модель,
  onRevoke,
}: {
  provider: string
  ключ: ModelKey | null
  модель: string
  onRevoke: () => void
}) {
  const t = useT()
  const завести = useAddModelKey()
  const выбрать = useSetProviderModel()
  const обновить = useRefreshProviderModels()
  const модели = useProviderModels(provider, !!ключ)

  const [строка, setСтрока] = useState('')
  const [меняем, setМеняем] = useState(false)
  const [беда, setБеда] = useState<string | null>(null)
  // Что человек только что выбрал, пока правка едет в службу: без этого поле на
  // мгновение возвращается к прежнему значению и выглядит как «не сохранилось».
  const [свежая, setСвежая] = useState<string | null>(null)

  const выбрана = свежая ?? модель
  const список = модели.data?.models ?? []

  async function записать() {
    setБеда(null)
    try {
      await завести.mutateAsync({ provider, key: строка.trim() })
      setСтрока('')
      setМеняем(false)
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <div className="flex flex-col gap-s2 rounded-sm border border-line bg-surface-2 px-s3 py-s3">
      <div className="flex flex-wrap items-center gap-s2">
        <Icon name="key" size={18} className={ключ ? 'text-ok' : 'text-muted'} />
        <span className="font-semibold text-ink-strong">{provider}</span>
        {ключ ? (
          <>
            <span className="font-mono text-sm text-muted">…{ключ.last4}</span>
            <span className="text-xs text-muted">
              {t('settings.keys.created')}: {formatDate(ключ.created_at)}
            </span>
            <div className="ml-auto flex items-center gap-s2">
              <Button variant="ghost" size="sm" onClick={() => setМеняем((было) => !было)}>
                {t('settings.providers.replace')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={onRevoke}
                aria-label={`${t('settings.keys.revoke')} ${provider}`}
              >
                <Icon name="trash" size={16} />
                {t('settings.keys.revoke')}
              </Button>
            </div>
          </>
        ) : (
          <Chip tone="muted">{t('settings.providers.noKey')}</Chip>
        )}
      </div>

      {(!ключ || меняем) && (
        <div className="flex flex-wrap items-end gap-s2">
          <Input
            label={t('settings.providers.keyLabel')}
            hint={t('settings.providers.keyHint')}
            type="password"
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            wrapperClassName="min-w-[16rem] flex-1"
            value={строка}
            onChange={(e) => setСтрока(e.target.value)}
          />
          <Button
            variant="primary"
            loading={завести.isPending}
            disabled={строка.trim().length < 8}
            onClick={() => void записать()}
          >
            <Icon name="plus" size={16} />
            {ключ ? t('settings.providers.replace') : t('settings.keys.add')}
          </Button>
        </div>
      )}
      {беда && <p className="text-sm text-err">{беда}</p>}

      {ключ && (
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-end gap-s2">
            <div className="min-w-[16rem] flex-1">
              <ModelCombobox
                id={`model-${provider}`}
                label={t('settings.providers.model')}
                value={выбрана}
                models={список}
                loading={модели.isLoading || выбрать.isPending}
                onChange={(значение) => {
                  // Своё значение впереди ответа службы: без этого поле на
                  // мгновение возвращается к прежнему и выглядит как «не
                  // сохранилось».
                  setСвежая(значение)
                  выбрать.mutate({ provider, model: значение },
                                 { onSettled: () => setСвежая(null) })
                }}
              />
            </div>
            <Button
              variant="ghost"
              size="sm"
              loading={обновить.isPending}
              onClick={() => обновить.mutate(provider)}
            >
              <Icon name="refresh" size={16} />
              {t('settings.providers.refresh')}
            </Button>
          </div>
          <p className="text-xs text-muted">
            {модели.data?.source === 'preset'
              ? t(`settings.providers.note.${модели.data.note || 'error'}`)
              : t('settings.providers.modelHint', { n: список.length })}
          </p>
        </div>
      )}
    </div>
  )
}
