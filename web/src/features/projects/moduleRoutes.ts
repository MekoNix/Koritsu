/**
 * moduleRoutes — куда ведёт кнопка «открыть в модуле» со страницы проекта.
 *
 * `app/shell/moduleLinks.ts` (файл каркаса) знает адрес *раздела* модуля —
 * того, что стоит в сайдбаре. Здесь другое знание: адрес *экрана работы* по
 * конкретному проекту, то есть адрес с идентификатором. Держать оба в одной
 * таблице нельзя — у них разная форма и разные владельцы: раздел заводит
 * каркас, экран работы заводит агент модуля.
 *
 * Адреса — те, о которых договорились агенты ночи:
 *
 *     reports     /reports/<id проекта>
 *     flowcharts  /flowcharts/<id проекта>
 *     uml         /uml/<id проекта>
 *
 * Модуля, которого здесь нет, на странице проекта не будет вовсе, даже если
 * служба его отдала: ссылка в никуда — ошибка (решение владельца), а «скоро»
 * запрещено брифом.
 */
import type { IconName } from '@/ui'

export type ProjectModuleLink = {
  /** Куда вести. Аргумент — идентификатор проекта. */
  href: (projectId: string) => string
  icon: IconName
  /** Переменная цвета модуля из темы. */
  colorVar: string
}

export const PROJECT_MODULE_LINKS: Record<string, ProjectModuleLink> = {
  reports: {
    href: (id) => `/reports/${id}`,
    icon: 'file',
    colorVar: '--mod-reports',
  },
  flowcharts: {
    href: (id) => `/flowcharts/${id}`,
    icon: 'flowchart',
    colorVar: '--mod-flowcharts',
  },
  uml: {
    href: (id) => `/uml/${id}`,
    icon: 'uml',
    colorVar: '--mod-uml',
  },
}

/** Есть ли у модуля экран работы по проекту. */
export function projectModuleLink(moduleId: string): ProjectModuleLink | undefined {
  return PROJECT_MODULE_LINKS[moduleId]
}
