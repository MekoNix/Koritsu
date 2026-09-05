/**
 * moduleLinks — где на сайте живёт модуль службы.
 *
 * `GET /api/modules` отдаёт `{id, title, routes}`, где `routes` — префикс
 * маршрутов API, а не адрес страницы. Соответствие «модуль службы → страница
 * сайта» знает только сайт, и лежит оно здесь одной таблицей.
 *
 * Правило брифа держится само собой: пункт сайдбара строится из ответа службы,
 * а служба неготовые модули не отдаёт вовсе. Модуль, которому здесь ещё нет
 * строки, в меню не попадёт — и это правильнее, чем пункт, ведущий в никуда.
 *
 * Как добавить модуль: строка сюда + маршрут в своём
 * `features/<область>/routes.tsx` + ключ перевода `shell.nav.<id>`.
 */
import type { IconName } from '@/ui'

export type ModuleLink = {
  /** Адрес страницы на сайте. */
  path: string
  icon: IconName
  /** Переменная цвета модуля из темы (`--mod-*`), если он у неё есть. */
  colorVar?: string
}

export const MODULE_LINKS: Record<string, ModuleLink> = {
  reports: { path: '/reports', icon: 'file', colorVar: '--mod-reports' },
  kadai: { path: '/kadai', icon: 'tasks', colorVar: '--mod-kadai' },
  flowcharts: { path: '/flowcharts', icon: 'flowchart', colorVar: '--mod-flowcharts' },
  uml: { path: '/uml', icon: 'uml', colorVar: '--mod-uml' },
}
