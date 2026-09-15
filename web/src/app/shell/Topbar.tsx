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
 *
 * **Узкий экран (≤ 640 px).** Слева встаёт кнопка меню — сайдбара на телефоне нет,
 * он выезжает по ней (`AppShell`). У «Поиска» и «Агента» остаются иконки: подписи
 * и сочетания клавиш не помещаются, а клавиатуры у телефона нет. Подпись при этом
 * не пропадает для скринридера.
 */
import { useState } from 'react'
import { useLocation } from 'react-router-dom'

import { useT } from '@/i18n'
import { hasOwnTutor, toggleAgentPanel, useAgentPanelOpen } from '@/features/agent'
import { SearchPalette } from '@/features/search/SearchPalette'
import { hotkeyLabel, useActionHotkey, useHotkeyBinding } from '@/lib/hotkeys'
import { Button, Icon } from '@/ui'

import { Breadcrumbs } from './breadcrumbs'
import { JobsMenu } from './JobsMenu'
import { NotificationsBell } from './NotificationsBell'
import { UserMenu } from './UserMenu'

export type TopbarProps = {
  /** Открыть выезжающее меню узкого экрана. */
  onOpenMenu?: () => void
  /** Открыто ли оно — для `aria-expanded` кнопки. */
  menuOpen?: boolean
}

export function Topbar({ onOpenMenu, menuOpen = false }: TopbarProps = {}) {
  const t = useT()
  const agentOpen = useAgentPanelOpen()
  const [searchOpen, setSearchOpen] = useState(false)
  // На разделе со своим репетитором («Доска») кнопки общей панели нет: панель
  // там не открывается, а кнопка, которая ничего не делает, хуже её отсутствия.
  const свойАгент = hasOwnTutor(useLocation().pathname)

  // Сочетания — по действию, а не буквой: человек вправе переназначить их в
  // настройках (`/settings/hotkeys`), и подсказка на кнопке обязана показывать
  // то, что и правда сработает.
  const поиск = useHotkeyBinding('search')
  const агент = useHotkeyBinding('agent')

  useActionHotkey('search', () => setSearchOpen((open) => !open))

  return (
    <header className="sticky top-0 z-20 flex h-topbar items-center gap-s3 bg-[color-mix(in_srgb,var(--bg)_68%,transparent)] px-s4 backdrop-blur-theme max-[640px]:gap-s1 max-[640px]:px-s2">
      {onOpenMenu && (
        <Button
          variant="ghost"
          size="lg"
          iconOnly
          className="-ml-1 text-ink min-[641px]:hidden"
          aria-label={t('shell.sidebar.open')}
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          onClick={onOpenMenu}
        >
          <Icon name="menu" size={22} />
        </Button>
      )}

      <div className="min-w-0 flex-1">
        <Breadcrumbs />
      </div>

      <div className="flex shrink-0 items-center gap-s2 rounded-full border border-line bg-surface px-1.5 py-1 shadow-1 max-[640px]:gap-0.5 max-[640px]:px-1">
        <Button
          variant="ghost"
          size="sm"
          className="rounded-full text-ink max-[640px]:min-h-[40px] max-[640px]:px-2.5"
          aria-haspopup="dialog"
          aria-expanded={searchOpen}
          onClick={() => setSearchOpen(true)}
        >
          <Icon name="search" size={16} />
          <span className="max-[640px]:sr-only">{t('shell.search.label')}</span>
          <kbd className="rounded-sm border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted max-[640px]:hidden">
            {hotkeyLabel(поиск)}
          </kbd>
        </Button>

        {!свойАгент && (
          <Button
            variant="agent"
            size="sm"
            className="rounded-full max-[640px]:min-h-[40px] max-[640px]:px-2.5"
            aria-expanded={agentOpen}
            onClick={toggleAgentPanel}
          >
            <Icon name="agent" size={16} />
            <span className="max-[640px]:sr-only">{t('shell.agent.label')}</span>
            <kbd className="rounded-sm border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted max-[640px]:hidden">
              {hotkeyLabel(агент)}
            </kbd>
          </Button>
        )}

        <span aria-hidden="true" className="mx-0.5 h-4 w-px bg-line max-[640px]:hidden" />

        <JobsMenu />
        <NotificationsBell />

        <span aria-hidden="true" className="mx-0.5 h-4 w-px bg-line max-[640px]:hidden" />

        <UserMenu />
      </div>

      <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} />
    </header>
  )
}
