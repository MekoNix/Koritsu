/**
 * ModelKeysSection — свои ключи поставщиков моделей.
 *
 * Карточка раздела «Конфигурация агентов»: стоит под выбором пресета, потому
 * что ключ — это то, чем выбранный пресет оплачивается.
 *
 * Служба никогда не возвращает ключ и не может: наружу уезжают поставщик,
 * четыре последних знака и даты (`keys/models.py: ModelKey.to_dict`). Поэтому
 * здесь нет ни «показать», ни «изменить» — только завести и отозвать.
 *
 * Списка «чем платится каждый поставщик» здесь нет: он один на раздел и стоит
 * рядом с выбором пресета, где на него и смотрят (`AgentSection`). Два
 * одинаковых списка на одном экране человек читает как два разных.
 *
 * Тост здесь один — на отказ. «Ключ добавлен» тостом не показывается: общее
 * правило (тосты — на завершение фоновой задачи и на ошибку), а сама
 * удача видна тем, что ключ появился в списке.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { errorField, errorText } from '@/api'
import { t as translate, useT } from '@/i18n'
import {
  Button,
  Card,
  Chip,
  Dialog,
  EmptyState,
  ErrorState,
  Icon,
  Input,
  Row,
  Select,
  SkeletonLines,
  useToast,
} from '@/ui'

import { useAddModelKey, useKeyProviders, useModelKeys, useRevokeModelKey } from './api'
import { formatDate } from './format'
import type { ModelKey } from './types'

const schema = z.object({
  provider: z.string().min(1, { message: translate('settings.valid.providerRequired') }),
  // Тот же вид, что проверяет служба (`keys/service.КЛЮЧ_RE`): печатные знаки
  // без пробелов, от 8 до 512. Проверка здесь — чтобы не гонять заведомо
  // кривое по сети; настоящую пригодность ключа покажет вызов поставщика.
  key: z
    .string()
    .trim()
    .min(8, { message: translate('settings.valid.keyRequired') })
    .max(512, { message: translate('settings.valid.keyLong') })
    .regex(/^[\x21-\x7e]+$/, { message: translate('settings.valid.keyFormat') }),
})

type Values = z.infer<typeof schema>

export function ModelKeysSection() {
  const t = useT()
  const toast = useToast()
  const list = useModelKeys()
  const providers = useKeyProviders()
  const add = useAddModelKey()
  const revoke = useRevokeModelKey()
  const [toRevoke, setToRevoke] = useState<ModelKey | null>(null)

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { provider: '', key: '' },
  })

  const providerNames = providers.data?.providers ?? []

  async function submit(values: Values) {
    try {
      await add.mutateAsync(values)
      form.reset({ provider: values.provider, key: '' })
    } catch (e) {
      // Отказ службы разбирается по коду: `where` называет поле, и тогда
      // ошибка садится в поле, а не улетает тостом мимо глаз.
      const field = errorField(e)
      if (field === 'provider' || field === 'key') {
        form.setError(field, { message: errorText(e) })
        return
      }
      toast.fail(e)
    }
  }

  async function doRevoke() {
    if (!toRevoke) return
    try {
      await revoke.mutateAsync(toRevoke.id)
      setToRevoke(null)
    } catch (e) {
      toast.fail(e)
    }
  }

  return (
    <>
      <Card title={t('settings.keys.title')} desc={t('settings.keys.text')}>
        {list.isLoading && <SkeletonLines count={3} />}
        {list.error && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}

        {list.data && list.data.length === 0 && (
          <EmptyState
            compact
            icon="key"
            title={t('settings.keys.empty')}
            text={t('settings.keys.emptyHint')}
          />
        )}

        {list.data && list.data.length > 0 && (
          <ul className="flex flex-col gap-s2">
            {list.data.map((key) => (
              <li
                key={key.id}
                className="flex flex-wrap items-center gap-s3 rounded-sm border border-line bg-surface-2 px-s3 py-s2"
              >
                <Icon name="key" size={18} className="text-muted" />
                <span className="font-semibold text-ink-strong">{key.provider}</span>
                <span className="font-mono text-sm text-muted">…{key.last4}</span>
                <span className="ml-auto text-xs text-muted">
                  {t('settings.keys.created')}: {formatDate(key.created_at)}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setToRevoke(key)}
                  aria-label={`${t('settings.keys.revoke')} ${key.provider}`}
                >
                  <Icon name="trash" size={16} />
                  {t('settings.keys.revoke')}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t('settings.keys.add')} desc={t('settings.keys.replaceHint')}>
        <form className="flex flex-col gap-s3" onSubmit={form.handleSubmit(submit)} noValidate>
          <Select
            label={t('settings.keys.provider')}
            error={form.formState.errors.provider?.message}
            disabled={providers.isLoading}
            {...form.register('provider')}
          >
            <option value="">—</option>
            {providerNames.map((provider) => (
              <option key={provider} value={provider}>
                {provider}
              </option>
            ))}
          </Select>
          <Input
            label={t('settings.keys.value')}
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder={t('settings.keys.valuePlaceholder')}
            className="font-mono"
            error={form.formState.errors.key?.message}
            {...form.register('key')}
          />
          <Button
            type="submit"
            variant="primary"
            className="self-start"
            loading={add.isPending}
            disabled={providers.isLoading}
          >
            <Icon name="plus" size={16} />
            {t('settings.keys.add')}
          </Button>
        </form>
      </Card>

      <Dialog
        open={toRevoke !== null}
        onOpenChange={(open) => !open && setToRevoke(null)}
        title={t('settings.keys.revokeTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setToRevoke(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button variant="danger" loading={revoke.isPending} onClick={() => void doRevoke()}>
              {t('settings.keys.revoke')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">
          {t('settings.keys.revokeText', {
            provider: toRevoke?.provider ?? '',
            last4: toRevoke?.last4 ?? '',
          })}
        </p>
        {toRevoke && (
          <div className="mt-s3">
            <Row label={t('settings.keys.last4')}>
              <Chip tone="muted">…{toRevoke.last4}</Chip>
            </Row>
          </div>
        )}
      </Dialog>
    </>
  )
}
