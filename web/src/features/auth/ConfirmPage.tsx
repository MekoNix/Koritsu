/**
 * Подтверждение почты по ссылке из письма.
 *
 * Формы здесь нет: человек уже сделал всё, что от него требовалось, — открыл
 * ссылку. Поэтому запрос уходит сам, а экран показывает одно из трёх: идёт
 * проверка, подтверждено, ссылка не годится.
 *
 * Запрос отправляется ровно один раз на код: повторное подтверждение отдаёт
 * `invalid_token`, и без этой защиты перерисовка превращала бы удачу в отказ.
 */
import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api, unwrap } from '@/api'
import { errorText } from '@/api/errors'
import { useT } from '@/i18n'
import { Button, Icon, Spinner } from '@/ui'

import { AuthHeading, AuthLayout } from './AuthLayout'
import { FormError } from './FormError'

export function ConfirmPage() {
  const t = useT()
  const [params] = useSearchParams()
  const token = params.get('token')
  const sent = useRef(false)

  const confirm = useMutation({
    mutationFn: (value: string) =>
      unwrap(api.POST('/api/auth/confirm', { body: { token: value } })),
  })

  const { mutate } = confirm
  useEffect(() => {
    if (!token || sent.current) return
    sent.current = true
    mutate(token)
  }, [token, mutate])

  if (!token) {
    return (
      <AuthLayout>
        <AuthHeading title={t('auth.confirm.title')} text={t('auth.valid.tokenMissing')} />
        <Button asChild variant="secondary">
          <Link to="/auth/login">{t('auth.confirm.toLogin')}</Link>
        </Button>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <AuthHeading title={t('auth.confirm.title')} />
      {confirm.isPending && (
        <p className="flex items-center gap-s2 text-sm text-muted">
          <Spinner size={16} />
          {t('auth.confirm.working')}
        </p>
      )}
      {confirm.isError && <FormError text={errorText(confirm.error)} />}
      {confirm.isSuccess && (
        <div className="flex flex-col items-start gap-s3">
          <Icon name="checkCircle" size={36} className="text-ok" />
          <p className="text-md text-ink-strong">{t('auth.confirm.okTitle')}</p>
          <p className="text-sm text-muted">{t('auth.confirm.okText')}</p>
        </div>
      )}
      {!confirm.isPending && (
        <Button asChild variant={confirm.isSuccess ? 'primary' : 'secondary'} className="mt-s4">
          <Link to="/auth/login">{t('auth.confirm.toLogin')}</Link>
        </Button>
      )}
    </AuthLayout>
  )
}
