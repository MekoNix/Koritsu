/**
 * Регистрация. `POST /api/auth/register` заводит аккаунт и отправляет письмо с
 * подтверждением; войти до подтверждения нельзя (`403 email_not_confirmed`).
 *
 * Поэтому у страницы два состояния: форма и «письмо отправлено». Второе — не
 * тост и не строчка под кнопкой: человеку надо уйти в почтовый ящик, и экран
 * обязан это сказать так, чтобы он не тыкал «зарегистрироваться» второй раз.
 *
 * Ник — обязательное поле: им человека зовут на всех
 * экранах, и спросить его позже было бы поздно — пришлось бы заводить экран
 * «представьтесь» между входом и работой. Отказы службы (`invalid_nickname`,
 * `nickname_taken`) приходят с адресом поля и встают под ним же.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'

import { api, unwrap } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, Input, PasswordInput } from '@/ui'

import { AuthHeading, AuthLayout } from './AuthLayout'
import { FormError } from './FormError'
import { registerSchema, type RegisterValues } from './schemas'
import { useAuthError } from './useAuthForm'

export function RegisterPage() {
  const t = useT()
  const [sentTo, setSentTo] = useState<string | null>(null)

  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: '', nickname: '', password: '' },
  })
  const { formError, handle, reset } = useAuthError(form.setError)

  const signUp = useMutation({
    mutationFn: (values: RegisterValues) =>
      unwrap(api.POST('/api/auth/register', { body: values })),
    onSuccess: (_data, values) => setSentTo(values.email),
    onError: (e) => handle(e, ['email', 'nickname', 'password']),
  })

  if (sentTo) {
    return (
      <AuthLayout>
        <div className="flex flex-col items-start gap-s3">
          <Icon name="mail" size={36} className="text-accent" />
          <AuthHeading
            title={t('auth.register.sentTitle')}
            text={t('auth.register.sentText', { email: sentTo })}
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
      <AuthHeading title={t('auth.register.title')} />
      <form
        className="flex flex-col gap-s4"
        noValidate
        onSubmit={form.handleSubmit((values) => {
          reset()
          signUp.mutate(values)
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
        <Input
          label={t('auth.field.nickname')}
          autoComplete="nickname"
          placeholder={t('auth.hint.nicknamePlaceholder')}
          hint={t('auth.hint.nickname')}
          error={form.formState.errors.nickname?.message}
          {...form.register('nickname')}
        />
        <PasswordInput
          label={t('auth.field.password')}
          autoComplete="new-password"
          hint={t('auth.hint.password')}
          error={form.formState.errors.password?.message}
          {...form.register('password')}
        />
        <Button type="submit" variant="primary" size="lg" loading={signUp.isPending}>
          {t('auth.register.submit')}
        </Button>
      </form>

      <div className="mt-s5 text-center text-sm">
        <Link to="/auth/login">{t('auth.register.toLogin')}</Link>
      </div>
    </AuthLayout>
  )
}
