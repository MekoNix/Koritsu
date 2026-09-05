/**
 * moduleRoutes — куда ведёт кнопка «открыть в модуле» со страницы проекта.
 *
 * `app/shell/moduleLinks.ts` (файл каркаса) знает адрес *раздела* модуля —
 * того, что стоит в сайдбаре. Здесь другое знание: адрес *экрана работы* по
 * конкретному проекту, то есть адрес с идентификатором. Держать оба в одной
 * таблице нельзя — у них разная форма и разное назначение: раздел ведёт в
 * список модуля, экран работы — к конкретному проекту.
 *
 * Адреса экранов работы:
 *
 *     reports     /reports/<id проекта>
 *     kadai       /kadai/<id проекта>
 *     flowcharts  /flowcharts/<id проекта>
 *     uml         /uml/<id проекта>
 *
 * Модуля, которого здесь нет, на странице проекта не будет вовсе, даже если
 * служба его отдала: ссылка в никуда — ошибка, а «скоро» запрещено правилом
 * интерфейса.
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
  kadai: {
    href: (id) => `/kadai/${id}`,
    icon: 'tasks',
    colorVar: '--mod-kadai',
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
