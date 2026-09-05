/**
 * UserDialog — карточка человека: план, право админа, лимиты, блокировка.
 *
 * **План — выпадающий список из справочника** (`GET /api/admin/plans`), а не
 * поле ввода: служба принимает только имена оттуда и на
 * любое другое отвечает `unknown_plan`. Поле ввода предлагало бы человеку
 * набрать то, за что откажут, и опечатка обнаруживалась бы отказом.
 *
 * **Лимиты заменяются целиком.** Так решила служба, и форма это повторяет:
 * пустое поле означает «вернуть значение плана», а не «оставить прежнее».
 * Иначе правка «поставь квоту» однажды сохранила бы месячный потолок, который
 * администратор как раз убирал.
 *
 * **Блокировка — отдельной кнопкой и с подтверждением, а не полем формы.**
 * Это не правка карточки, а действие: оно отзывает все сессии человека и
 * закрывает ему вход, и случиться от промаха по «Сохранить» не должно.
 * Подтверждение называет, что именно случится, — «вы уверены?» без объяснения
 * нажимают не глядя.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import {
  Avatar,
  Button,
  Card,
  Chip,
  Dialog,
  Icon,
  Input,
  Row,
  Select,
  Switch,
  useToast,
} from '@/ui'

import { formatBytes, formatDate, formatUnits } from '@/features/settings/format'

import { useAdminPlans, usePatchAdminUser } from './api'
import { userStatus } from './table'
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
  const plans = useAdminPlans()
  const [confirming, setConfirming] = useState(false)
  const blocked = user?.blocked_at != null

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

  /**
   * Заблокировать или разблокировать. Отдельным запросом, а не полем формы:
   * это действие, а не правка, и подтверждается оно своим окном.
   */
  async function переключить_блокировку() {
    if (!user) return
    try {
      await patch.mutateAsync({ userId: user.id, patch: { blocked: !blocked } })
      setConfirming(false)
      onClose()
    } catch (e) {
      toast.error(errorText(e))
    }
  }

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
    <>
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
                {/* Ник крупно, почта под ним: карточку открывают, чтобы понять,
                  кто это, — а зовут человека ником. */}
                <div className="break-all font-semibold text-ink-strong">{user.nickname}</div>
                <div className="break-all text-xs text-muted">{user.email}</div>
                <div className="break-all font-mono text-xs text-muted">{user.id}</div>
              </div>
              <div className="ml-auto flex flex-wrap gap-s2">
                {user.is_admin && <Chip tone="info">{t('admin.users.role.admin')}</Chip>}
                {user.deleted_at && <Chip tone="err">{t('admin.users.status.deleted')}</Chip>}
                {blocked && <Chip tone="err">{t('admin.users.status.blocked')}</Chip>}
                {!user.email_confirmed && (
                  <Chip tone="warn">{t('admin.users.status.unconfirmed')}</Chip>
                )}
              </div>
            </div>

            <form className="flex flex-col gap-s4" onSubmit={form.handleSubmit(submit)} noValidate>
              <Select
                label={t('admin.card.plan')}
                hint={t('admin.card.planHint')}
                error={form.formState.errors.plan?.message}
                {...form.register('plan')}
              >
                {/* План человека, которого в справочнике нет, остаётся в списке
                  своей строкой: без неё список молча подменил бы его первым
                  попавшимся при первом же сохранении карточки. */}
                {(plans.data ?? []).some((п) => п.plan === user.plan) ? null : (
                  <option value={user.plan}>{user.plan}</option>
                )}
                {(plans.data ?? []).map((план) => (
                  <option key={план.plan} value={план.plan}>
                    {план.plan}
                  </option>
                ))}
              </Select>

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
              {user.blocked_at && (
                <Row label={t('admin.card.blocked')}>{formatDate(user.blocked_at)}</Row>
              )}
              <Row label={t('admin.users.col.status')}>
                {t(`admin.users.status.${userStatus(user)}`)}
              </Row>
            </div>

            <div className="flex flex-wrap items-center gap-s3 rounded-md border border-line p-s3">
              <span className="min-w-0 flex-1 text-xs text-muted">
                {t(blocked ? 'admin.card.unblockHint' : 'admin.card.blockHint')}
              </span>
              <Button
                variant={blocked ? 'secondary' : 'danger'}
                onClick={() => setConfirming(true)}
                disabled={patch.isPending}
              >
                <Icon name={blocked ? 'unlock' : 'lock'} size={16} />
                {t(blocked ? 'admin.card.unblock' : 'admin.card.block')}
              </Button>
            </div>
          </div>
        )}
      </Dialog>

      {/* Подтверждение — отдельным окном рядом, а не внутри карточки: два
          вложенных модальных окна ловят фокус друг у друга, и «Отмена» во
          внутреннем закрывала бы оба. */}
      <Dialog
        open={confirming}
        onOpenChange={(o) => !o && setConfirming(false)}
        title={t(blocked ? 'admin.card.unblockTitle' : 'admin.card.blockTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant={blocked ? 'primary' : 'danger'}
              loading={patch.isPending}
              onClick={() => void переключить_блокировку()}
            >
              {t(blocked ? 'admin.card.unblock' : 'admin.card.block')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">
          {t(blocked ? 'admin.card.unblockConfirm' : 'admin.card.blockConfirm', {
            who: user?.nickname ?? '',
          })}
        </p>
      </Dialog>
    </>
  )
}
