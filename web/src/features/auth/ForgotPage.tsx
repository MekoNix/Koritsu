/**
 * Запрос ссылки на смену пароля.
 *
 * Служба отвечает одинаково, есть такой аккаунт или нет, — и текст на экране
 * такой же осторожный («если аккаунт существует…»). Сказать «такой почты у нас
 * нет» значило бы отдать любому желающему список зарегистрированных адресов.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'

import { api, unwrap } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, Input } from '@/ui'

import { AuthHeading, AuthLayout } from './AuthLayout'
import { FormError } from './FormError'
import { forgotSchema, type ForgotValues } from './schemas'
import { useAuthError } from './useAuthForm'

export function ForgotPage() {
  const t = useT()
  const [sentTo, setSentTo] = useState<string | null>(null)

  const form = useForm<ForgotValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: '' },
  })
  const { formError, handle, reset } = useAuthError(form.setError)

  const ask = useMutation({
    mutationFn: (values: ForgotValues) =>
      unwrap(api.POST('/api/auth/password/forgot', { body: values })),
    onSuccess: (_data, values) => setSentTo(values.email),
    onError: (e) => handle(e, ['email']),
  })

  if (sentTo) {
    return (
      <AuthLayout>
        <div className="flex flex-col items-start gap-s3">
          <Icon name="mail" size={36} className="text-accent" />
          <AuthHeading
            title={t('auth.forgot.sentTitle')}
            text={t('auth.forgot.sentText', { email: sentTo })}
          />
          <Button asChild variant="secondary">
            <Link to="/auth/login">{t('auth.forgot.toLogin')}</Link>
          </Button>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <AuthHeading title={t('auth.forgot.title')} text={t('auth.forgot.text')} />
      <form
        className="flex flex-col gap-s4"
        noValidate
        onSubmit={form.handleSubmit((values) => {
          reset()
          ask.mutate(values)
        })}
      >
        <FormError text={formError} />
        <Input
          label={t('auth.field.email')}
          type="email"
          autoComplete="username"
          placeholder={t('auth.hint.emailPlaceholder')}
          error={form.formState.errors.email?.message}
          {...form.register('email')}
        />
        <Button type="submit" variant="primary" size="lg" loading={ask.isPending}>
          {t('auth.forgot.submit')}
        </Button>
      </form>

      <div className="mt-s5 text-center text-sm">
        <Link to="/auth/login">{t('auth.forgot.toLogin')}</Link>
      </div>
    </AuthLayout>
  )
}
