/**
 * UserDialog — карточка человека: план, право админа, личные лимиты.
 *
 * Это всё, что умеет `PATCH /api/admin/users/{id}` (`UserPatchIn`): плана-
 * справочника нет, поэтому план вписывается строкой; блокировки аккаунта нет
 * вовсе, поэтому кнопки «отключить» здесь тоже нет — она бы врала.
 *
 * **Лимиты заменяются целиком.** Так решила служба, и форма это повторяет:
 * пустое поле означает «вернуть значение плана», а не «оставить прежнее».
 * Иначе правка «поставь квоту» однажды сохранила бы месячный потолок, который
 * владелец как раз убирал.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Avatar, Button, Card, Chip, Dialog, Input, Row, Switch, useToast } from '@/ui'

import { formatBytes, formatDate, formatUnits } from '@/features/settings/format'

import { usePatchAdminUser } from './api'
import type { AdminUser, UserPatch } from './types'

/** Пустая строка — «нет значения», а не ноль: ноль был бы настоящим лимитом. */
const optionalNumber = z
  .string()
  .trim()
  .refine((v) => v === '' || (/^\d+$/.test(v) && Number.isSafeInteger(Number(v))), {
    message: '—',
  })

const schema = z.object({
  plan: z.string().trim().max(32),
  is_admin: z.boolean(),
  monthly_units: optionalNumber,
  quota_bytes: optionalNumber,
})

type Values = z.infer<typeof schema>

function limitOf(user: AdminUser, key: string): string {
  const value = user.limits?.[key]
  return typeof value === 'number' ? String(value) : ''
}

export function UserDialog({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const t = useT()
  const toast = useToast()
  const patch = usePatchAdminUser()

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { plan: '', is_admin: false, monthly_units: '', quota_bytes: '' },
  })
  const { reset } = form

  // Карточка одна на всю таблицу, поэтому при смене человека форма
  // перезаполняется: без этого во второй карточке остались бы поля первой.
  useEffect(() => {
    if (!user) return
    reset({
      plan: user.plan,
      is_admin: user.is_admin,
      monthly_units: limitOf(user, 'monthly_units'),
      quota_bytes: limitOf(user, 'quota_bytes'),
    })
  }, [user, reset])

  async function submit(values: Values) {
    if (!user) return
    const limits: Record<string, number> = {}
    if (values.monthly_units !== '') limits.monthly_units = Number(values.monthly_units)
    if (values.quota_bytes !== '') limits.quota_bytes = Number(values.quota_bytes)
    const body: UserPatch = { plan: values.plan, is_admin: values.is_admin, limits }
    try {
      await patch.mutateAsync({ userId: user.id, patch: body })
      onClose()
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  return (
    <Dialog
      open={user !== null}
      onOpenChange={(open) => !open && onClose()}
      title={t('admin.card.title')}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.action.cancel')}
          </Button>
          <Button
            variant="primary"
            loading={patch.isPending}
            onClick={() => void form.handleSubmit(submit)()}
          >
            {t('admin.card.save')}
          </Button>
        </>
      }
    >
      {user && (
        <div className="flex flex-col gap-s4">
          <div className="flex flex-wrap items-center gap-s3">
            <Avatar id={user.id} size={44} label={user.email} />
            <div className="min-w-0">
              <div className="break-all font-semibold text-ink-strong">{user.email}</div>
              <div className="break-all font-mono text-xs text-muted">{user.id}</div>
            </div>
            <div className="ml-auto flex flex-wrap gap-s2">
              {user.is_admin && <Chip tone="info">{t('admin.users.role.admin')}</Chip>}
              {user.deleted_at && <Chip tone="err">{t('admin.users.status.deleted')}</Chip>}
              {!user.email_confirmed && (
                <Chip tone="warn">{t('admin.users.status.unconfirmed')}</Chip>
              )}
            </div>
          </div>

          <form className="flex flex-col gap-s4" onSubmit={form.handleSubmit(submit)} noValidate>
            <Input
              label={t('admin.card.plan')}
              hint={t('admin.card.planHint')}
              error={form.formState.errors.plan?.message}
              {...form.register('plan')}
            />

            <label className="flex cursor-pointer items-start gap-s3">
              <Switch {...form.register('is_admin')} />
              <span>
                <span className="block text-sm font-medium text-ink">
                  {t('admin.card.isAdmin')}
                </span>
                <span className="block text-xs text-muted">{t('admin.card.isAdminHint')}</span>
              </span>
            </label>

            <Card title={t('admin.card.limits')} desc={t('admin.card.limitsHint')}>
              <div className="grid gap-s3 sm:grid-cols-2">
                <Input
                  label={t('admin.card.monthlyUnits')}
                  inputMode="numeric"
                  className="font-mono"
                  error={form.formState.errors.monthly_units?.message}
                  {...form.register('monthly_units')}
                />
                <Input
                  label={t('admin.card.quotaBytes')}
                  inputMode="numeric"
                  className="font-mono"
                  hint={formatBytes(user.quota_bytes)}
                  error={form.formState.errors.quota_bytes?.message}
                  {...form.register('quota_bytes')}
                />
              </div>
            </Card>
          </form>

          <div className="flex flex-col">
            <Row label={t('admin.card.spent')}>
              {formatUnits(user.spent_units)} {t('common.unit.units')}
            </Row>
            <Row label={t('admin.card.bytesUsed')}>
              {formatBytes(user.bytes_used)} / {formatBytes(user.quota_bytes)}
            </Row>
            <Row label={t('admin.card.created')}>{formatDate(user.created_at)}</Row>
            {user.deleted_at && (
              <Row label={t('admin.card.deleted')}>{formatDate(user.deleted_at)}</Row>
            )}
          </div>

          <p className="text-xs text-muted">{t('admin.card.blockHint')}</p>
        </div>
      )}
    </Dialog>
  )
}
