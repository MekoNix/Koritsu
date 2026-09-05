/**
 * Topbar — шапка.
 *
 * Правило макетов, дословно: «шапка без собственного фона: полупрозрачная
 * подложка с размытием, а поиск / агент / фоновые задачи / колокольчик /
 * профиль собраны в отдельную „таблетку“». Отсюда две вещи в разметке:
 * у самой шапки заливки нет (фон страницы виден насквозь, содержимое под ней
 * размывается), а справа стоит одна скруглённая группа, а не пять кнопок в ряд.
 *
 * Кнопка «Поиск» и `Ctrl+K` открывают одну и ту же палитру
 * (`features/search`): она живёт здесь, потому что и кнопка, и сочетание — это
 * шапка, а искать человек может с любого экрана.
 *
 * Кнопка «Агент» открывает и закрывает панель агента (`features/agent`) — ту
 * же, что `Ctrl+J`. Самой панели шапка не знает: она держит только признак
 * открытости (`useAgentPanelOpen`), а живёт панель в оболочке. Иначе шапка
 * оказалась бы родителем окна, которое стоит поверх всей страницы.
 */
import { useState } from 'react'

import { useT } from '@/i18n'
import { toggleAgentPanel, useAgentPanelOpen } from '@/features/agent'
import { SearchPalette } from '@/features/search/SearchPalette'
import { hotkeyLabel, useActionHotkey, useHotkeyBinding } from '@/lib/hotkeys'
import { Button, Icon } from '@/ui'

import { Breadcrumbs } from './breadcrumbs'
import { JobsMenu } from './JobsMenu'
import { NotificationsBell } from './NotificationsBell'
import { UserMenu } from './UserMenu'

export function Topbar() {
  const t = useT()
  const agentOpen = useAgentPanelOpen()
  const [searchOpen, setSearchOpen] = useState(false)

  // Сочетания — по действию, а не буквой: человек вправе переназначить их в
  // настройках (`/settings/hotkeys`), и подсказка на кнопке обязана показывать
  // то, что и правда сработает.
  const поиск = useHotkeyBinding('search')
  const агент = useHotkeyBinding('agent')

  useActionHotkey('search', () => setSearchOpen((open) => !open))

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
          aria-haspopup="dialog"
          aria-expanded={searchOpen}
          onClick={() => setSearchOpen(true)}
        >
          <Icon name="search" size={16} />
          {t('shell.search.label')}
          <kbd className="rounded-sm border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
            {hotkeyLabel(поиск)}
          </kbd>
        </Button>

        <Button
          variant="agent"
          size="sm"
          className="rounded-full"
          aria-expanded={agentOpen}
          onClick={toggleAgentPanel}
        >
          <Icon name="agent" size={16} />
          {t('shell.agent.label')}
          <kbd className="rounded-sm border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
            {hotkeyLabel(агент)}
          </kbd>
        </Button>

        <span aria-hidden="true" className="mx-0.5 h-4 w-px bg-line" />

        <JobsMenu />
        <NotificationsBell />

        <span aria-hidden="true" className="mx-0.5 h-4 w-px bg-line" />

        <UserMenu />
      </div>

      <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} />
    </header>
  )
}
