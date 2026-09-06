/**
 * TokensSection — ключи для скриптов (`/api/tokens`).
 *
 * Главное свойство экрана — **строка ключа показывается один раз**. Служба
 * хранит только отпечаток (`tokens/models.py`), поэтому потерянный ключ
 * отзывают и заводят заново, а не восстанавливают. Отсюда две вещи в коде:
 * строка живёт в состоянии компонента и нигде больше (в кэш TanStack Query
 * она не кладётся), и окно с ней закрывается только руками — самозакрытие по
 * таймеру отняло бы у человека ключ, который он не успел скопировать.
 *
 * Отозванные ключи из списка не исчезают: отозванный ключ обязан отличаться
 * от несуществующего, иначе непонятно, отозвал ты его или он пропал сам.
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
  CopyButton,
  Dialog,
  EmptyState,
  ErrorState,
  Icon,
  Input,
  Row,
  SkeletonLines,
  useToast,
} from '@/ui'

import { useApiTokens, useCreateApiToken, useRevokeApiToken } from './api'
import { formatDate } from './format'
import { TOKEN_SCOPES, type ApiToken, type ApiTokenCreated } from './types'

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(1, { message: translate('settings.valid.nameRequired') })
    .max(64, { message: translate('settings.valid.nameLong') }),
  scopes: z.array(z.string()).min(1, { message: translate('settings.valid.scopesRequired') }),
})

type Values = z.infer<typeof schema>

export function TokensSection() {
  const t = useT()
  const toast = useToast()
  const list = useApiTokens()
  const create = useCreateApiToken()
  const revoke = useRevokeApiToken()

  const [creating, setCreating] = useState(false)
  /** Строка ключа, показанная один раз. Живёт ровно до закрытия окна. */
  const [issued, setIssued] = useState<ApiTokenCreated | null>(null)
  const [toRevoke, setToRevoke] = useState<ApiToken | null>(null)

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', scopes: [] },
  })

  function openCreate() {
    form.reset({ name: '', scopes: [] })
    setCreating(true)
  }

  async function submit(values: Values) {
    try {
      const token = await create.mutateAsync(values)
      setCreating(false)
      setIssued(token)
    } catch (e) {
      const field = errorField(e)
      if (field === 'name' || field === 'scopes') {
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
      <Card
        title={t('settings.tokens.title')}
        desc={t('settings.tokens.text')}
        action={
          <Button variant="primary" size="sm" onClick={openCreate}>
            <Icon name="plus" size={16} />
            {t('settings.tokens.create')}
          </Button>
        }
      >
        {list.isLoading && <SkeletonLines count={3} />}
        {list.error && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}

        {list.data && list.data.length === 0 && (
          <EmptyState
            compact
            icon="file"
            title={t('settings.tokens.empty')}
            text={t('settings.tokens.emptyHint')}
            action={
              <Button variant="secondary" size="sm" onClick={openCreate}>
                {t('settings.tokens.create')}
              </Button>
            }
          />
        )}

        {list.data && list.data.length > 0 && (
          <ul className="flex flex-col gap-s2">
            {list.data.map((token) => {
              const revoked = token.revoked_at !== null
              return (
                <li
                  key={token.id}
                  className="flex flex-col gap-s2 rounded-sm border border-line bg-surface-2 px-s3 py-s2"
                >
                  <div className="flex flex-wrap items-center gap-s2">
                    <span className="font-semibold text-ink-strong">{token.name}</span>
                    <span className="font-mono text-xs text-muted">kor_{token.prefix}…</span>
                    <Chip tone={revoked ? 'err' : 'ok'}>
                      {revoked ? t('settings.tokens.isRevoked') : t('settings.tokens.active')}
                    </Chip>
                    {!revoked && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="ml-auto"
                        onClick={() => setToRevoke(token)}
                      >
                        <Icon name="trash" size={16} />
                        {t('settings.tokens.revoke')}
                      </Button>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {token.scopes.map((scope) => (
                      <Chip key={scope} tone="accent">
                        {scope}
                      </Chip>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-s4 text-xs text-muted">
                    <span>
                      {t('settings.keys.created')}: {formatDate(token.created_at)}
                    </span>
                    <span>
                      {t('settings.tokens.lastUsed')}:{' '}
                      {token.last_used_at
                        ? formatDate(token.last_used_at)
                        : t('settings.tokens.never')}
                    </span>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Card>

      {/* Создание */}
      <Dialog
        open={creating}
        onOpenChange={setCreating}
        title={t('settings.tokens.createTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="primary"
              loading={create.isPending}
              onClick={() => void form.handleSubmit(submit)()}
            >
              {t('settings.tokens.create')}
            </Button>
          </>
        }
      >
        <form className="flex flex-col gap-s4" onSubmit={form.handleSubmit(submit)} noValidate>
          <Input
            label={t('settings.tokens.name')}
            placeholder={t('settings.tokens.namePlaceholder')}
            autoComplete="off"
            error={form.formState.errors.name?.message}
            {...form.register('name')}
          />
          <fieldset className="flex flex-col gap-s2">
            <legend className="mb-1.5 text-sm font-medium text-ink">
              {t('settings.tokens.scopes')}
            </legend>
            {TOKEN_SCOPES.map((scope) => (
              <label key={scope} className="flex cursor-pointer items-start gap-s2 text-sm">
                <input
                  type="checkbox"
                  value={scope}
                  className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
                  {...form.register('scopes')}
                />
                <span>
                  <span className="text-ink">{t(`settings.tokens.scope.${scope}`)}</span>{' '}
                  <span className="font-mono text-xs text-muted">{scope}</span>
                </span>
              </label>
            ))}
            {form.formState.errors.scopes && (
              <p className="text-xs text-err">{form.formState.errors.scopes.message}</p>
            )}
          </fieldset>
        </form>
      </Dialog>

      {/* Показ строки ключа — один раз за его жизнь. */}
      <Dialog
        open={issued !== null}
        onOpenChange={(open) => !open && setIssued(null)}
        title={t('settings.tokens.onceTitle')}
        footer={
          <Button variant="primary" onClick={() => setIssued(null)}>
            {t('common.action.close')}
          </Button>
        }
      >
        <p className="text-sm text-ink">{t('settings.tokens.onceText')}</p>
        {issued && (
          <div className="mt-s3 flex flex-col gap-s3">
            <div className="flex items-center gap-s2 rounded-sm border border-line bg-surface-2 p-s3">
              <code className="min-w-0 flex-1 break-all font-mono text-sm text-ink-strong">
                {issued.token}
              </code>
              <CopyButton text={issued.token} />
            </div>
            <div className="flex flex-col">
              <Row label={t('settings.tokens.name')}>{issued.name}</Row>
              <Row label={t('settings.tokens.prefix')}>
                <span className="font-mono text-xs">kor_{issued.prefix}</span>
              </Row>
              <Row label={t('settings.tokens.scopes')}>{issued.scopes.join(', ')}</Row>
            </div>
          </div>
        )}
      </Dialog>

      {/* Отзыв */}
      <Dialog
        open={toRevoke !== null}
        onOpenChange={(open) => !open && setToRevoke(null)}
        title={t('settings.tokens.revokeTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setToRevoke(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button variant="danger" loading={revoke.isPending} onClick={() => void doRevoke()}>
              {t('settings.tokens.revoke')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">
          {t('settings.tokens.revokeText', { name: toRevoke?.name ?? '' })}
        </p>
      </Dialog>
    </>
  )
}
