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
 *
 * Четвёртый пункт, «Админка», виден только владельцу службы и правилу состава
 * не противоречит: в сайдбар админка не выводится никому, и это единственное
 * место, откуда в неё попадают не по памяти адреса. Ведёт он на её собственный
 * домен (там она и живёт), поэтому переход — обычный переход браузера, а не
 * роутером: между origin'ами роутер не ходит.
 */
import { useNavigate } from 'react-router-dom'

import { useIsAdmin, useLogout, useMe } from '@/api/hooks'
import { useT } from '@/i18n'
import { адресАдминки, админкаНаЭтомИмени, доменАдминки } from '@/lib/adminHost'
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
  const { isAdmin } = useIsAdmin()
  const logout = useLogout()

  const name = me?.nickname ?? ''
  // Домена нет (машина разработчика, стенд) — админка живёт там же, где сайт,
  // и пункт ведёт обычным переходом. Есть — уводим на её имя.
  const открытьАдминку = () => {
    if (доменАдминки() && !админкаНаЭтомИмени()) window.location.assign(адресАдминки())
    else navigate('/admin')
  }

  return (
    <MenuRoot>
      <MenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="gap-s2 pl-1 pr-2"
          aria-label={t('shell.user.menu')}
        >
          {/* Своя картинка, если человек её загрузил: `me` живёт одним ключом
              кэша, и загрузка в настройках кладёт свежий профиль прямо в него —
              шапка меняется тем же рендером, без перезагрузки страницы. */}
          <Avatar id={me?.id} size={26} version={me?.avatar_version} />
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
        {isAdmin ? (
          <MenuItem icon={<Icon name="shield" size={18} />} onSelect={открытьАдминку}>
            {t('shell.user.admin')}
          </MenuItem>
        ) : null}
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
