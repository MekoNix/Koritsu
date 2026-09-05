/**
 * SecuritySection — выход на всех устройствах.
 *
 * Больше здесь показывать нечего, и это состояние службы, а не недоделка:
 * смены пароля из кабинета нет (пароль меняется по письму со страницы
 * восстановления), включения второго фактора нет, удаления аккаунта нет.
 * Придумывать кнопки, за которыми нет маршрута, нельзя — они врут.
 *
 * `logout-all` гасит и текущую сессию тоже, поэтому после удачи человек
 * уезжает на вход своим ходом: `useMe` вернёт `null`, и `RequireAuth` уведёт.
 * Мы делаем это явно, не дожидаясь первого 401 на случайном запросе.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { errorText } from '@/api'
import { useMe } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, Card, Chip, Dialog, Icon, Row, useToast } from '@/ui'

import { useLogoutEverywhere } from './api'

export function SecuritySection() {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const me = useMe()
  const logoutAll = useLogoutEverywhere()
  const [asking, setAsking] = useState(false)

  async function doLogoutAll() {
    try {
      await logoutAll.mutateAsync()
      setAsking(false)
      navigate('/auth/login', { replace: true })
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  return (
    <>
      <Card title={t('settings.security.title')} desc={t('settings.security.text')}>
        <div className="flex flex-col">
          <Row label={t('settings.security.totp')}>
            <Chip tone={me.data?.totp_enabled ? 'ok' : 'muted'}>
              {me.data?.totp_enabled ? t('settings.profile.totpOn') : t('settings.profile.totpOff')}
            </Chip>
          </Row>
        </div>
        <p className="text-xs text-muted">{t('settings.security.totpHint')}</p>
      </Card>

      <Card title={t('settings.security.logoutAll')} desc={t('settings.security.logoutAllHint')}>
        <Button variant="danger" className="self-start" onClick={() => setAsking(true)}>
          <Icon name="logout" size={16} />
          {t('settings.security.logoutAll')}
        </Button>
      </Card>

      <Card tone="danger" title={t('settings.security.danger')}>
        <p className="text-sm text-muted">{t('settings.security.dangerText')}</p>
      </Card>

      <Dialog
        open={asking}
        onOpenChange={setAsking}
        title={t('settings.security.logoutAllTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAsking(false)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={logoutAll.isPending}
              onClick={() => void doLogoutAll()}
            >
              {t('settings.security.logoutAll')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">{t('settings.security.logoutAllText')}</p>
      </Dialog>
    </>
  )
}
