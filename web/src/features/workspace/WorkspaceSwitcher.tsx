/**
 * WorkspaceSwitcher — в каком пространстве человек работает, и как его сменить.
 *
 * **Почему в сайдбаре, а не в меню имени.** Меню имени в макете `01-shell`
 * закрыто и состоит ровно из трёх пунктов («Настройки / Дашборд / Выйти»);
 * дописывать туда четвёртый значило бы спорить с макетом. Пространство же —
 * это не про человека, а про то, где лежат его работы: сайдбар ведёт по
 * работам, и рамка, в которой они показаны, стоит над его пунктами. Место —
 * под логотипом, выше заголовка «Модули», чтобы список модулей остался ровно
 * таким, каким его задал бриф.
 *
 * Полоски у активного пункта здесь нет и быть не может: это не пункт меню, а
 * кнопка с выпадающим списком.
 *
 * **Кнопка отвечает на вопрос «где я», а не только «куда перейти».** Над именем
 * стоит слово «Пространство»: без него строка читалась как ещё один пункт меню,
 * и человек, у которого пространств два, не понимал, в котором из них лежат
 * работы на экране. Ровно за этим же имя пространства повторено подписью у
 * свёрнутого сайдбара (`title`) — там от кнопки остаётся одна буква.
 *
 * Свёрнутый сайдбар показывает только первую букву пространства — как и
 * остальные пункты, у которых остаются одни иконки.
 *
 * Здесь же стоит `useWorkspaceScopeReset`: переключатель в оболочке ровно один,
 * и это единственное место, где сброс кэша при смене пространства заводится
 * один раз на приложение, не занимая собой общий каркас.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  setCurrentWorkspaceId,
  useCurrentWorkspace,
  useCurrentWorkspaceId,
  useWorkspaceScopeReset,
} from '@/api/hooks'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import {
  Button,
  Dialog,
  Icon,
  Input,
  MenuContent,
  MenuItem,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
  Skeleton,
  useToast,
} from '@/ui'
import { errorText } from '@/api'

import { useCreateWorkspace, useWorkspaces } from './data'
import { workspaceLabel } from './types'
import { usePersonalName } from './usePersonalName'

export function WorkspaceSwitcher({ collapsed }: { collapsed: boolean }) {
  const t = useT()
  const navigate = useNavigate()
  const текущее = useCurrentWorkspace()
  const выбран = useCurrentWorkspaceId()
  const список = useWorkspaces()
  const [creating, setCreating] = useState(false)

  // Смена пространства меняет всё, что показано на экране: списки чужого
  // пространства переключение не переживают.
  useWorkspaceScopeReset()

  // Личное пространство зовётся `<ник>-workspace`; строкам, заведённым до
  // появления ника, служба дала имя `Personal` — их называет `usePersonalName`.
  const личное = usePersonalName()
  const имя = текущее.data ? workspaceLabel(текущее.data, личное) : ''

  return (
    <>
      <MenuRoot>
        <MenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t('workspace.switcher.label')}
            // Подпись нужна свёрнутому сайдбару: там от кнопки остаётся буква,
            // и «где я» иначе не прочитать вовсе.
            title={имя ? t('workspace.switcher.current', { name: имя }) : undefined}
            className={cn(
              'h-auto w-full justify-start gap-s2 border border-line bg-surface-2 px-2 py-1.5 text-ink',
              collapsed && 'w-11 justify-center px-0',
            )}
          >
            <span
              aria-hidden="true"
              className="grid h-[22px] w-[22px] flex-none place-items-center rounded-sm bg-accent-bg font-mono text-[12px] font-bold uppercase text-accent"
            >
              {имя.slice(0, 1) || '·'}
            </span>
            {!collapsed &&
              (текущее.isLoading ? (
                <Skeleton className="h-3 w-24" />
              ) : (
                <>
                  <span className="flex min-w-0 flex-1 flex-col items-start leading-tight">
                    {/* Слово над именем: строка отвечает на «где я», а не
                        притворяется ещё одним пунктом меню. */}
                    <span className="text-[10px] uppercase tracking-wider text-muted">
                      {t('workspace.switcher.caption')}
                    </span>
                    <span className="w-full truncate text-left text-sm font-medium">
                      {имя || t('workspace.switcher.label')}
                    </span>
                  </span>
                  <Icon name="chevronDown" size={14} className="text-muted" />
                </>
              ))}
          </Button>
        </MenuTrigger>

        <MenuContent align="start" className="w-[240px]">
          {(список.data ?? []).map((ws) => {
            const этот = ws.personal ? выбран === null || выбран === ws.id : выбран === ws.id
            return (
              <MenuItem
                key={ws.id}
                onSelect={() => setCurrentWorkspaceId(ws.personal ? null : ws.id)}
                icon={
                  <Icon name="check" size={16} className={этот ? 'text-accent' : 'opacity-0'} />
                }
              >
                <span className="min-w-0 flex-1 truncate">{workspaceLabel(ws, личное)}</span>
              </MenuItem>
            )
          })}
          {список.isLoading && (
            <div className="p-s2">
              <Skeleton className="h-3 w-full" />
            </div>
          )}
          <MenuSeparator />
          <MenuItem icon={<Icon name="users" size={16} />} onSelect={() => navigate('/workspace')}>
            {t('workspace.switcher.manage')}
          </MenuItem>
          <MenuItem icon={<Icon name="plus" size={16} />} onSelect={() => setCreating(true)}>
            {t('workspace.switcher.create')}
          </MenuItem>
        </MenuContent>
      </MenuRoot>

      <CreateDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}

/** Новое пространство. Создатель сразу владелец — так устроена служба. */
function CreateDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const t = useT()
  const toast = useToast()
  const create = useCreateWorkspace()
  const [name, setName] = useState('')

  const завести = () => {
    const имя = name.trim()
    if (!имя) return
    create.mutate(имя, {
      onSuccess: (ws) => {
        // Заведённое пространство сразу становится текущим: заводят его затем,
        // чтобы в нём работать.
        setCurrentWorkspaceId(ws.id)
        setName('')
        onOpenChange(false)
      },
      onError: (беда) => toast.error(errorText(беда)),
    })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('workspace.create.title')}
      description={t('workspace.create.desc')}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('workspace.cancel')}
          </Button>
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!name.trim()}
            onClick={завести}
          >
            {t('workspace.create.submit')}
          </Button>
        </>
      }
    >
      <Input
        label={t('workspace.create.name')}
        value={name}
        maxLength={200}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') завести()
        }}
      />
    </Dialog>
  )
}
