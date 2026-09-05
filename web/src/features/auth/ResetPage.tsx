/**
 * Смена пароля по ссылке из письма.
 *
 * Код берётся из адреса (`/auth/reset?token=…`) — ровно так его кладёт в
 * ссылку служба (`accounts/mail.py`). Кода нет — форму показывать незачем:
 * человек попал сюда мимо письма, и единственное осмысленное действие для
 * него — запросить письмо заново.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router-dom'

import { api, unwrap } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, PasswordInput } from '@/ui'

import { AuthHeading, AuthLayout } from './AuthLayout'
import { FormError } from './FormError'
import { resetSchema, type ResetValues } from './schemas'
import { useAuthError } from './useAuthForm'

export function ResetPage() {
  const t = useT()
  const [params] = useSearchParams()
  const token = params.get('token')

  const form = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: '', repeat: '' },
  })
  const { formError, handle, reset } = useAuthError(form.setError)

  const change = useMutation({
    mutationFn: (values: ResetValues) =>
      unwrap(
        api.POST('/api/auth/password/reset', {
          body: { token: token ?? '', password: values.password },
        }),
      ),
    onError: (e) => handle(e, ['password']),
  })

  if (!token) {
    return (
      <AuthLayout>
        <AuthHeading title={t('auth.reset.title')} text={t('auth.valid.tokenMissing')} />
        <Button asChild variant="secondary">
          <Link to="/auth/forgot">{t('auth.forgot.submit')}</Link>
        </Button>
      </AuthLayout>
    )
  }

  if (change.isSuccess) {
    return (
      <AuthLayout>
        <div className="flex flex-col items-start gap-s3">
          <Icon name="checkCircle" size={36} className="text-ok" />
          <AuthHeading title={t('auth.reset.okTitle')} text={t('auth.reset.okText')} />
          <Button asChild variant="primary">
            <Link to="/auth/login">{t('auth.confirm.toLogin')}</Link>
          </Button>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <AuthHeading title={t('auth.reset.title')} />
      <form
        className="flex flex-col gap-s4"
        noValidate
        onSubmit={form.handleSubmit((values) => {
          reset()
          change.mutate(values)
        })}
      >
        <FormError text={formError} />
        <PasswordInput
          label={t('auth.field.passwordNew')}
          autoComplete="new-password"
          hint={t('auth.hint.password')}
          error={form.formState.errors.password?.message}
          {...form.register('password')}
        />
        <PasswordInput
          label={t('auth.field.passwordRepeat')}
          autoComplete="new-password"
          error={form.formState.errors.repeat?.message}
          {...form.register('repeat')}
        />
        <Button type="submit" variant="primary" size="lg" loading={change.isPending}>
          {t('auth.reset.submit')}
        </Button>
      </form>
    </AuthLayout>
  )
}
