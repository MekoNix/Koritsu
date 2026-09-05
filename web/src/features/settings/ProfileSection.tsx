/**
 * ProfileSection — то, что служба знает о человеке.
 *
 * Раздел получился читающим, и это не упрощение: у `users` нет ни имени, ни
 * часового пояса, ни картинки, а `GET /api/auth/me` отдаёт id, почту, план,
 * подтверждение почты, второй фактор и дату (`accounts/routes.py: профиль()`).
 * Маршрута «поменять профиль» в службе нет вовсе. Поэтому здесь показывается
 * ровно то, что есть, и честно сказано, чего нет, — а не форма с полями,
 * которые некуда отправить.
 *
 * Аватар генеративный и другим быть не может: загрузки картинки служба не
 * умеет, а ходить за ней к постороннему сервису — утечка почты на чужой домен
 * (`ui/Avatar.tsx`).
 */
import { useMe } from '@/api/hooks'
import { useT } from '@/i18n'
import { Avatar, Card, Chip, ErrorState, Row, SkeletonLines } from '@/ui'

import { formatDate } from './format'

export function ProfileSection() {
  const t = useT()
  const me = useMe()

  if (me.isLoading) {
    return (
      <Card title={t('settings.profile.title')}>
        <SkeletonLines count={5} />
      </Card>
    )
  }
  if (me.error) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />
  if (!me.data) return null

  const user = me.data
  return (
    <Card title={t('settings.profile.title')}>
      <div className="flex flex-wrap items-center gap-s4">
        <Avatar id={user.id} size={72} label={user.email} />
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="break-all font-display text-lg font-semibold text-ink-strong">
            {user.email}
          </div>
          <div className="flex flex-wrap gap-s2">
            <Chip tone="accent">{user.plan}</Chip>
            <Chip tone={user.email_confirmed ? 'ok' : 'warn'}>
              {user.email_confirmed
                ? t('settings.profile.confirmed')
                : t('settings.profile.notConfirmed')}
            </Chip>
            <Chip tone={user.totp_enabled ? 'ok' : 'muted'}>
              {user.totp_enabled ? t('settings.profile.totpOn') : t('settings.profile.totpOff')}
            </Chip>
          </div>
          <p className="max-w-[52ch] text-xs text-muted">{t('settings.profile.avatarHint')}</p>
        </div>
      </div>

      <div className="flex flex-col">
        <Row label={t('settings.profile.email')}>
          <span className="break-all">{user.email}</span>
          <span className="ml-s2 text-xs text-muted">{t('settings.profile.emailHint')}</span>
        </Row>
        <Row label={t('settings.profile.plan')}>{user.plan}</Row>
        <Row label={t('settings.profile.id')}>
          <span className="break-all font-mono text-xs">{user.id}</span>
        </Row>
        <Row label={t('settings.profile.created')}>{formatDate(user.created_at)}</Row>
      </div>

      <p className="text-xs text-muted">{t('settings.profile.readonly')}</p>
    </Card>
  )
}
