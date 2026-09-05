/**
 * CreateUserDialog — «завести человека»: почта, план, ник → ссылка сброса.
 *
 * Пароля здесь нет и не будет. Служба писем не шлёт, поэтому администратор
 * получает **ссылку сброса пароля** и передаёт её человеку
 * сам; пароль тот ставит обычной страницей `/auth/reset`. Придумывать человеку
 * пароль и пересылать его — это пароль, который знают двое.
 *
 * **Ссылка показывается один раз**, как строка ключа для скриптов
 * (`settings/TokensSection`): открытой служба её нигде не хранит — в базе
 * лежит только sha256. Поэтому окно с ссылкой отдельное, закрывается кнопкой,
 * и в нём стоит кнопка копирования, а не одна голая строка.
 *
 * План — выпадающий список из справочника (`GET /api/admin/plans`), а не поле
 * ввода: служба принимает только имена оттуда и на любое другое отвечает
 * `unknown_plan`.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, CopyButton, Dialog, Input, Row, Select, useToast } from '@/ui'

import { useAdminPlans, useCreateAdminUser } from './api'
import type { CreatedUser } from './types'

const schema = z.object({
  email: z.string().trim().min(3).max(320),
  plan: z.string().trim().max(32),
  nickname: z.string().trim().max(128),
})

type Values = z.infer<typeof schema>

export function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT()
  const toast = useToast()
  const plans = useAdminPlans()
  const create = useCreateAdminUser()
  const [issued, setIssued] = useState<CreatedUser | null>(null)

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', plan: '', nickname: '' },
  })
  const { reset } = form

  // Форма чистится при каждом открытии: почта прошлого человека в поле — это
  // заведённый по ошибке второй аккаунт.
  useEffect(() => {
    if (open) reset({ email: '', plan: '', nickname: '' })
  }, [open, reset])

  async function submit(values: Values) {
    try {
      const итог = await create.mutateAsync({
        email: values.email,
        // Пустые поля не отправляются вовсе: пустой ник служба поняла бы как
        // «возьми из почты», а пустой план — как «поставь план с именем ''».
        ...(values.plan ? { plan: values.plan } : {}),
        ...(values.nickname ? { nickname: values.nickname } : {}),
      })
      setIssued(итог)
      onClose()
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(o) => !o && onClose()}
        title={t('admin.create.title')}
        description={t('admin.create.text')}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="primary"
              loading={create.isPending}
              onClick={() => void form.handleSubmit(submit)()}
            >
              {t('admin.create.submit')}
            </Button>
          </>
        }
      >
        <form className="flex flex-col gap-s4" onSubmit={form.handleSubmit(submit)} noValidate>
          <Input
            label={t('admin.create.email')}
            type="email"
            autoComplete="off"
            error={form.formState.errors.email?.message}
            {...form.register('email')}
          />
          <Input
            label={t('admin.create.nickname')}
            hint={t('admin.create.nicknameHint')}
            autoComplete="off"
            error={form.formState.errors.nickname?.message}
            {...form.register('nickname')}
          />
          <Select label={t('admin.create.plan')} {...form.register('plan')}>
            <option value="">{t('admin.create.planDefault')}</option>
            {(plans.data ?? []).map((план) => (
              <option key={план.plan} value={план.plan}>
                {план.plan}
              </option>
            ))}
          </Select>
        </form>
      </Dialog>

      {/* Показ ссылки — один раз за её жизнь. */}
      <Dialog
        open={issued !== null}
        onOpenChange={(o) => !o && setIssued(null)}
        title={t('admin.create.onceTitle')}
        footer={
          <Button variant="primary" onClick={() => setIssued(null)}>
            {t('common.action.close')}
          </Button>
        }
      >
        <p className="text-sm text-ink">{t('admin.create.onceText')}</p>
        {issued && (
          <div className="mt-s3 flex flex-col gap-s3">
            <div className="flex items-center gap-s2 rounded-sm border border-line bg-surface-2 p-s3">
              <code className="min-w-0 flex-1 break-all font-mono text-sm text-ink-strong">
                {issued.reset_url}
              </code>
              <CopyButton text={issued.reset_url} />
            </div>
            <div className="flex flex-col">
              <Row label={t('admin.create.email')}>{issued.user.email}</Row>
              <Row label={t('admin.create.nickname')}>{issued.user.nickname}</Row>
              <Row label={t('admin.create.plan')}>{issued.user.plan}</Row>
            </div>
          </div>
        )}
      </Dialog>
    </>
  )
}
