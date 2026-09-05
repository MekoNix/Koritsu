/**
 * Вход. `POST /api/auth/login` ставит cookie сессии, а заодно (см. `csrf.py`)
 * и cookie CSRF, поэтому первый же изменяющий запрос после входа уходит с
 * заголовком без дополнительных действий.
 *
 * После входа человек возвращается туда, откуда его увели (`state.from`), а не
 * на дашборд: иначе ссылка на конкретный отчёт из письма теряется.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { api, unwrap } from '@/api'
import { keys } from '@/api/queryKeys'
import { useT } from '@/i18n'
import { Button, Input, PasswordInput } from '@/ui'

import { AuthHeading, AuthLayout } from './AuthLayout'
import { FormError } from './FormError'
import { loginSchema, type LoginValues } from './schemas'
import { useAuthError } from './useAuthForm'

export function LoginPage() {
  const t = useT()
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })
  const { formError, handle, reset } = useAuthError(form.setError)

  const login = useMutation({
    mutationFn: (values: LoginValues) => unwrap(api.POST('/api/auth/login', { body: values })),
    onSuccess: async () => {
      // Профиль перечитывается до перехода: иначе защищённый маршрут увидит
      // старое «не вошёл» и отправит обратно на вход.
      //
      // `refetchType: 'all'`, а не умолчание. Умолчание перечитывает только
      // ЖИВЫЕ запросы, а на странице входа профиль никто не спрашивает — он
      // лежит в кэше значением `null`, оставленным охраной маршрута, когда она
      // увела сюда с закрытого адреса. Без этой строки самый обычный путь
      // («открыл ссылку на работу → отправили на вход → вошёл») возвращал на
      // вход второй раз: `RequireAuth` успевал прочитать то самое `null`.
      // Найдено сквозной проверкой (`e2e/tests/flow.spec.ts`, последний шаг).
      await qc.invalidateQueries({ queryKey: keys.me, refetchType: 'all' })
      const from = (location.state as { from?: string } | null)?.from
      navigate(from ?? '/', { replace: true })
    },
    onError: (e) => handle(e, ['email', 'password']),
  })

  return (
    <AuthLayout>
      <AuthHeading title={t('auth.login.title')} />
      <form
        className="flex flex-col gap-s4"
        noValidate
        onSubmit={form.handleSubmit((values) => {
          reset()
          login.mutate(values)
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
        <PasswordInput
          label={t('auth.field.password')}
          autoComplete="current-password"
          error={form.formState.errors.password?.message}
          {...form.register('password')}
        />
        <Button type="submit" variant="primary" size="lg" loading={login.isPending}>
          {t('auth.login.submit')}
        </Button>
      </form>

      <div className="mt-s5 flex flex-col gap-s2 text-center text-sm">
        <Link to="/auth/forgot">{t('auth.login.toForgot')}</Link>
        <Link to="/auth/register">{t('auth.login.toRegister')}</Link>
      </div>
    </AuthLayout>
  )
}
