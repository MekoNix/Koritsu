/**
 * areas — деление сборки по областям сайта: резать сборку на части нужно
 * максимально.
 *
 * **Зачем.** До этого файла весь сайт был одним куском JS на 1,3 МБ: человек,
 * открывший форму входа, выкачивал вместе с ней и админку, и редактор кода на
 * схемах. Здесь каждая область грузится своим `import()`, то есть тогда, когда
 * на неё зашли, — и Rollup режет сборку по этим точкам сам.
 *
 * **Как это устроено и почему именно так.** Область объявляет свои маршруты у
 * себя (`features/<область>/routes.tsx`) и пишет их путями от корня сайта
 * (`projects/:projectId`, а не `:projectId`). Значит вложить их в маршрут вида
 * `projects/*` нельзя — React Router считал бы путь от `/projects` и получил
 * бы `/projects/projects`. Поэтому граница ленивой загрузки одна и стоит она
 * на `*` прямо под оболочкой: у такого маршрута «основание» пути остаётся
 * корнем, и вложенный `useRoutes` разбирает адреса ровно так же, как разбирал
 * бы верхний. Ни одна область при этом не переписывается.
 *
 * Какой кусок грузить, решает **первый отрезок адреса** (`/projects/p-1` →
 * `projects`). Список отрезков — ниже; область, которой в нём нет, попадает в
 * запасной путь, где грузятся все куски разом и адрес ищется среди всех
 * маршрутов. Запасной путь стоит здесь не для красоты: маршруты добавляют
 * несколько человек сразу, и забытая строка в списке обязана означать «чуть
 * медленнее», а не «страница пропала».
 *
 * Добавили область с новым отрезком адреса — допишите строку в `ЗАГРУЗЧИКИ`.
 */
import { Suspense, lazy, useMemo, type ComponentType } from 'react'
import { useLocation, useRoutes, type RouteObject } from 'react-router-dom'

import { SkeletonLines } from '@/ui'

import { NotFoundPage } from './NotFoundPage'

/** Что грузить под каким первым отрезком адреса. Пустая строка — корень сайта. */
const ЗАГРУЗЧИКИ: Record<string, () => Promise<RouteObject[]>> = {
  '': () => import('@/features/dashboard/routes').then((m) => m.dashboardRoutes),
  dashboard: () => import('@/features/dashboard/routes').then((m) => m.dashboardRoutes),
  projects: () => import('@/features/projects/routes').then((m) => m.projectsRoutes),
  reports: () => import('@/features/reports/routes').then((m) => m.reportsRoutes),
  kadai: () => import('@/features/kadai/routes').then((m) => m.kadaiRoutes),
  flowcharts: () => import('@/features/diagrams/routes').then((m) => m.diagramsRoutes),
  uml: () => import('@/features/diagrams/routes').then((m) => m.diagramsRoutes),
  diagrams: () => import('@/features/diagrams/routes').then((m) => m.diagramsRoutes),
  settings: () => import('@/features/settings/routes').then((m) => m.settingsRoutes),
  workspace: () => import('@/features/workspace/routes').then((m) => m.workspaceRoutes),
  admin: () => import('@/features/admin/routes').then((m) => m.adminRoutes),
}

/**
 * Запасной путь: адрес не из списка. Грузим всё и ищем среди всех маршрутов —
 * страница, которую забыли вписать в список выше, обязана открыться.
 */
async function всеОбласти(): Promise<RouteObject[]> {
  const части = await Promise.all(
    [...new Set(Object.values(ЗАГРУЗЧИКИ))].map((загрузить) => загрузить()),
  )
  return части.flat()
}

/**
 * Компоненты областей делаются один раз и запоминаются: `lazy()` на каждой
 * перерисовке — это новый тип компонента, а значит размонтирование поддерева и
 * повторная загрузка куска на каждый переход.
 */
const кэш = new Map<string, ComponentType>()

function областьКомпонент(ключ: string): ComponentType {
  const готовый = кэш.get(ключ)
  if (готовый) return готовый
  const загрузить = ЗАГРУЗЧИКИ[ключ] ?? всеОбласти
  const компонент = lazy(async () => {
    const маршруты = await загрузить()
    // Хвостовой `*` — свой у каждой области: адрес вроде `/projects/нет/такого`
    // должен давать «страница не найдена», а не пустоту.
    function AreaRoutes() {
      return useRoutes([...маршруты, { path: '*', element: <NotFoundPage /> }])
    }
    return { default: AreaRoutes }
  })
  кэш.set(ключ, компонент)
  return компонент
}

/**
 * Заглушка на время загрузки куска. Скелетон, а не «Загрузка…»: кусок приезжает
 * за десятки миллисекунд, и слово успевает мигнуть, а полосы — нет.
 */
function AreaFallback() {
  return (
    <div className="p-6">
      <SkeletonLines count={5} />
    </div>
  )
}

/** Область по адресу — с ленивой загрузкой её куска. */
export function AreaOutlet() {
  const { pathname } = useLocation()
  const ключ = pathname.split('/')[1] ?? ''
  const Area = useMemo(() => областьКомпонент(ключ), [ключ])
  return (
    <Suspense fallback={<AreaFallback />}>
      <Area />
    </Suspense>
  )
}
