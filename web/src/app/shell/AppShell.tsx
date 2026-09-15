/**
 * AppShell — общий каркас: сайдбар слева, шапка сверху, экран внутри.
 *
 * Здесь же открывается единственный на всё приложение поток событий человека
 * (`useUserEvents`): он гасит и зажигает колокольчик и выдаёт тосты на
 * завершение фоновых задач. Открывать его в экранах нельзя — сколько экранов,
 * столько было бы соединений.
 *
 * Состояние «сайдбар свёрнут» помнится в `localStorage`: бриф требует, чтобы
 * сворачивание происходило по кнопке, а не по наведению, — и значит выбор
 * человека обязан пережить перезагрузку.
 *
 * **Узкий экран (≤ 640 px).** Постоянная колонка сайдбара прячется, меню
 * выезжает слева по кнопке в шапке и закрывается переходом на другую страницу,
 * касанием мимо или `Esc`. Лист — модальное окно Radix: ловушка фокуса и
 * блокировка прокрутки под ним те же, что у диалогов. Поля экрана на телефоне
 * уже, чтобы содержимое не теряло ширину.
 */
import * as RadixDialog from '@radix-ui/react-dialog'
import { useCallback, useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { useUserEvents } from '@/api/hooks'
import { AgentPanel } from '@/features/agent'
import { useT } from '@/i18n'

import { BreadcrumbProvider } from './breadcrumbs'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

const KEY = 'koritsu.sidebar.collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function AppShell() {
  const t = useT()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [menuOpen, setMenuOpen] = useState(false)
  const { pathname } = useLocation()

  // Поток человека: один на приложение, живёт столько же, сколько оболочка.
  useUserEvents()

  // Переход по пункту меню закрывает выезжающее меню: страница уже другая.
  useEffect(() => {
    setMenuOpen(false)
  }, [pathname])

  const toggle = useCallback(() => {
    setCollapsed((was) => {
      const next = !was
      try {
        localStorage.setItem(KEY, next ? '1' : '0')
      } catch {
        // Не записалось — переживём: на этой вкладке состояние уже поменялось.
      }
      return next
    })
  }, [])

  return (
    <BreadcrumbProvider>
      <div className="flex min-h-screen">
        <Sidebar collapsed={collapsed} onToggle={toggle} className="max-[640px]:hidden" />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar onOpenMenu={() => setMenuOpen(true)} menuOpen={menuOpen} />
          {/* Потолок ширины и поля — переменными: рабочий экран (отчёт) снимает
              их на время своей жизни через `useWidePage`, остальные живут в
              обычной колонке. */}
          <main className="mx-auto w-full min-w-0 max-w-[var(--page-max,var(--content-max))] flex-1 p-[var(--page-pad,var(--space-5))] max-[640px]:p-[var(--page-pad,var(--space-3))]">
            <Outlet />
          </main>
        </div>
      </div>

      <RadixDialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
        <RadixDialog.Portal>
          <RadixDialog.Overlay className="fixed inset-0 z-[90] bg-overlay min-[641px]:hidden" />
          <RadixDialog.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 z-[91] flex w-[min(300px,86vw)] flex-col border-r border-line bg-surface shadow-2 min-[641px]:hidden"
          >
            <RadixDialog.Title className="sr-only">{t('shell.sidebar.modules')}</RadixDialog.Title>
            <Sidebar collapsed={false} mobile onToggle={() => setMenuOpen(false)} />
          </RadixDialog.Content>
        </RadixDialog.Portal>
      </RadixDialog.Root>

      {/* Панель агента: поверх любого экрана, немодальная, Ctrl+J. Смонтирована
          всегда — иначе горячая клавиша работала бы не отовсюду, а прогон
          обрывался бы закрытием окна. Пока закрыта, не рисует ничего. */}
      <AgentPanel />
    </BreadcrumbProvider>
  )
}
