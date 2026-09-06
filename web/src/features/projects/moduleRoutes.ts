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
 *     reports     /reports/<id проекта>, отдельный отчёт — /reports/<id>/<id отчёта>
 *     kadai       /kadai/<id проекта>, отдельное решение — /kadai/<id>/<id решения>
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
  /**
   * Куда вести от **одной записи журнала запусков**, если у модуля такой адрес
   * есть. У отчётов он есть, потому что отчётов в работе несколько: у каждого
   * свой бланк и свои значения, и общий адрес привёл бы человека не к тому
   * документу, на который он нажал. У решений — по той же причине: у каждого
   * своё условие и свой список блоков. У модулей, где документ на работу один,
   * поля нет, и строка журнала ведёт туда же, куда кнопка «открыть в модуле».
   */
  runHref?: (projectId: string, runId: string) => string
  icon: IconName
  /** Переменная цвета модуля из темы. */
  colorVar: string
}

export const PROJECT_MODULE_LINKS: Record<string, ProjectModuleLink> = {
  reports: {
    href: (id) => `/reports/${id}`,
    runHref: (id, runId) => `/reports/${id}/${runId}`,
    icon: 'file',
    colorVar: '--mod-reports',
  },
  kadai: {
    href: (id) => `/kadai/${id}`,
    // Решений в работе несколько — у каждого своё условие, свои файлы контекста
    // и свой список блоков, — поэтому строка журнала ведёт к своему решению, а
    // не к списку решений работы.
    runHref: (id, runId) => `/kadai/${id}/${runId}`,
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
