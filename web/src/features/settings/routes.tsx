/**
 * Маршруты области «Настройки».
 *
 * Раздел — часть адреса (`/settings/keys`), а не состояние страницы: на
 * настройки дают ссылку («вот здесь заводится ключ»), и кнопка «назад» в
 * браузере обязана возвращать на прошлый раздел, а не выкидывать из настроек.
 *
 * Как устроен договор с `app/routes.tsx` — см. `features/dashboard/routes.tsx`.
 */
import { Navigate, type RouteObject } from 'react-router-dom'

import { AgentSection } from './AgentSection'
import { AppearanceSection } from './AppearanceSection'
import { HotkeysSection } from './HotkeysSection'
import { ModelKeysSection } from './ModelKeysSection'
import { ProfileSection } from './ProfileSection'
import { SecuritySection } from './SecuritySection'
import { SettingsPage } from './SettingsPage'
import { TemplatesSection } from './TemplatesSection'
import { TokensSection } from './TokensSection'
import { UsageSection } from './UsageSection'

export const settingsRoutes: RouteObject[] = [
  {
    path: 'settings',
    element: <SettingsPage />,
    children: [
      { index: true, element: <Navigate to="profile" replace /> },
      { path: 'profile', element: <ProfileSection /> },
      { path: 'appearance', element: <AppearanceSection /> },
      { path: 'keys', element: <ModelKeysSection /> },
      { path: 'tokens', element: <TokensSection /> },
      { path: 'templates', element: <TemplatesSection /> },
      { path: 'hotkeys', element: <HotkeysSection /> },
      { path: 'agent', element: <AgentSection /> },
      { path: 'usage', element: <UsageSection /> },
      { path: 'security', element: <SecuritySection /> },
      // Неизвестный раздел — не «страница не найдена», а первый раздел:
      // человек всё-таки в настройках, и показывать ему пустоту незачем.
      { path: '*', element: <Navigate to="/settings/profile" replace /> },
    ],
  },
]
