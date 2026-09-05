/**
 * Topbar — шапка.
 *
 * Правка 2 макетов, дословно: «шапка без собственного фона: полупрозрачная
 * подложка с размытием, а поиск / агент / фоновые задачи / колокольчик /
 * профиль собраны в отдельную „таблетку“». Отсюда две вещи в разметке:
 * у самой шапки заливки нет (фон страницы виден насквозь, содержимое под ней
 * размывается), а справа стоит одна скруглённая группа, а не пять кнопок в ряд.
 *
 * Поиск и окно агента на этой ночи — заглушки: и то и другое делается ночью 2
 * (Ctrl+K по проектам и материалам, Ctrl+J — панель агента). Кнопки стоят на
 * своих местах и честно говорят, что пока не работают, — это лучше, чем
 * переставлять шапку через неделю.
 */
import { useT } from '@/i18n'
import { Button, Icon, useToast } from '@/ui'

import { Breadcrumbs } from './breadcrumbs'
import { JobsMenu } from './JobsMenu'
import { NotificationsBell } from './NotificationsBell'
import { UserMenu } from './UserMenu'

export function Topbar() {
  const t = useT()
  const toast = useToast()

  return (
    <header className="sticky top-0 z-20 flex h-topbar items-center gap-s3 bg-[color-mix(in_srgb,var(--bg)_68%,transparent)] px-s4 backdrop-blur-theme">
      <div className="min-w-0 flex-1">
        <Breadcrumbs />
      </div>

      <div className="flex items-center gap-s2 rounded-full border border-line bg-surface px-1.5 py-1 shadow-1">
        <Button
          variant="ghost"
          size="sm"
          className="rounded-full text-ink"
          onClick={() => toast.warn(t('shell.search.label'), t('shell.search.soon'))}
        >
          <Icon name="search" size={16} />
          {t('shell.search.label')}
          <kbd className="rounded-sm border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
            Ctrl K
          </kbd>
        </Button>

        <Button
          variant="agent"
          size="sm"
          className="rounded-full"
          onClick={() => toast.agent(t('shell.agent.label'), t('shell.agent.soon'))}
        >
          <Icon name="agent" size={16} />
          {t('shell.agent.label')}
          <kbd className="rounded-sm border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
            Ctrl J
          </kbd>
        </Button>

        <span aria-hidden="true" className="mx-0.5 h-4 w-px bg-line" />

        <JobsMenu />
        <NotificationsBell />

        <span aria-hidden="true" className="mx-0.5 h-4 w-px bg-line" />

        <UserMenu />
      </div>
    </header>
  )
}
