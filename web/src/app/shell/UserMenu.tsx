/**
 * UserMenu — аватар, имя и меню профиля.
 *
 * Состав меню задан правилом интерфейса дословно: Настройки, Дашборд, Выйти из
 * аккаунта. Ничего сверх этого сюда не дописывается — «Помощь» и «О программе»
 * разводят короткое меню в свалку, а правило на этот счёт закрыто.
 *
 * Аватар генеративный, из идентификатора (правило интерфейса); имя — **ник**.
 * Почты здесь нет вовсе: шапка видна на каждом экране, в том числе на
 * проекторе, а узнать по ней человек ничего не может — свой адрес он и так
 * знает. Нужна почта — она в настройках профиля.
 */
import { useNavigate } from 'react-router-dom'

import { useLogout, useMe } from '@/api/hooks'
import { useT } from '@/i18n'
import {
  Avatar,
  Button,
  Icon,
  MenuContent,
  MenuItem,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
} from '@/ui'

export function UserMenu() {
  const t = useT()
  const navigate = useNavigate()
  const { data: me } = useMe()
  const logout = useLogout()

  const name = me?.nickname ?? ''

  return (
    <MenuRoot>
      <MenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="gap-s2 pl-1 pr-2"
          aria-label={t('shell.user.menu')}
        >
          <Avatar id={me?.id} size={26} />
          <span className="max-w-[180px] truncate text-sm font-medium text-ink">{name}</span>
          <Icon name="chevronDown" size={14} className="text-muted" />
        </Button>
      </MenuTrigger>
      <MenuContent>
        <MenuItem icon={<Icon name="settings" size={18} />} onSelect={() => navigate('/settings')}>
          {t('shell.user.settings')}
        </MenuItem>
        <MenuItem icon={<Icon name="dashboard" size={18} />} onSelect={() => navigate('/')}>
          {t('shell.user.dashboard')}
        </MenuItem>
        <MenuSeparator />
        <MenuItem
          danger
          icon={<Icon name="logout" size={18} />}
          onSelect={() => {
            // Уводим на вход сразу, не дожидаясь ответа: сессия гасится и
            // cookie, и на службе, а держать человека на странице, куда его
            // уже не пускают, незачем.
            logout.mutate(undefined, {
              onSettled: () => navigate('/auth/login', { replace: true }),
            })
          }}
        >
          {t('shell.user.logout')}
        </MenuItem>
      </MenuContent>
    </MenuRoot>
  )
}
