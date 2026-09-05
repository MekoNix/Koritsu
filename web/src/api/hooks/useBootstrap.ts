/**
 * useBootstrap — один запрос, с которого начинается страница.
 *
 * Оболочке для первого экрана нужно пять вещей: кто вошёл, какие есть модули,
 * сколько осталось за месяц, в каких пространствах человек состоит и что лежит
 * в колокольчике. Раньше это были пять запросов, уходивших одновременно с
 * разных экранов; служба отдаёт их одним ответом (`GET /api/bootstrap`), и
 * здесь этот ответ раскладывается по тем же ключам кэша, из которых читают
 * `useMe`, `useModules`, `useUsage`, `useWorkspaces` и `useNotifications`.
 *
 * **Ключи, а не свой источник.** Хуки остаются прежними и продолжают знать
 * свои маршруты: сводка нужна загрузке страницы, а перечитать один расход
 * после задания — это один расход, а не пять ответов заново. Поэтому здесь
 * `setQueryData`, а не подмена `queryFn` у каждого хука.
 *
 * **Раскладка идёт внутри `queryFn`, до того как хук отдаст данные.** Это и
 * есть условие «один запрос при загрузке»: к моменту, когда охрана маршрута
 * пустит экраны рисоваться, кэш уже полон, и ни один хук оболочки не пойдёт в
 * сеть — у всех у них свой `staleTime`, и данные им приезжают свежими.
 *
 * `401` здесь не беда, а «не вошёл» — ровно как в `useMe`: сводка отвечает
 * тем же кодом, и охрана маршрута уводит на вход сама.
 */
import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { запомнитьДоменАдминки } from '@/lib/adminHost'

import { api, unwrap } from '../client'
import { isApiError } from '../errors'
import { keys } from '../queryKeys'
import type { Me, ModuleInfo, NotificationsPage, Usage } from '../types'

import type { Workspace } from './useCurrentWorkspace'
import { СКОЛЬКО_В_КОЛОКОЛЬЧИКЕ } from './useNotifications'

/**
 * `packages/api/bootstrap.py: сводка()` — всё для первого экрана одним ответом.
 *
 * Части — те же типы, что у отдельных маршрутов, а не их копии: служба строит
 * вложенные объекты теми же функциями, и поле, добавленное в карточку
 * пространства, обязано приезжать сюда само. Копия формы означала бы сайт,
 * которому одно и то же поле приходит по-разному в зависимости от того, каким
 * запросом он спросил.
 */
export type Bootstrap = {
  me: Me
  /**
   * Имя домена, на котором живёт админка, или пустая строка. Не часть
   * профиля: это настройка машины (`KORITSU_ADMIN_DOMAIN`), и в карточке
   * человека ей не место.
   */
  admin_domain: string
  modules: ModuleInfo[]
  usage: Usage
  workspaces: Workspace[]
  notifications: NotificationsPage
}

/**
 * Разложить сводку по ключам кэша.
 *
 * Ключи — те же самые, что у отдельных хуков, и берутся они из `queryKeys`, а
 * не пишутся строкой: разъехавшийся ключ здесь не сломал бы сборку, он просто
 * означал бы второй запрос за тем же самым — то есть ровно то, ради чего
 * сводка и заведена.
 */
function разложить(qc: ReturnType<typeof useQueryClient>, тело: Bootstrap): void {
  qc.setQueryData(keys.me, тело.me)
  // Не в кэш запросов: имя домена админки — не данные экрана, а настройка, по
  // которой решается, открывается ли `/admin` на этом имени вообще.
  запомнитьДоменАдминки(тело.admin_domain)
  qc.setQueryData(keys.modules, тело.modules)
  qc.setQueryData(keys.usage, тело.usage)
  qc.setQueryData([...keys.notifications, СКОЛЬКО_В_КОЛОКОЛЬЧИКЕ], тело.notifications)
  qc.setQueryData(keys.workspaces.list(false), тело.workspaces)
  // Личное пространство лежит в том же списке и стоит в нём первым. Отдельный
  // ключ у него потому, что переключатель спрашивает «где я сейчас», не зная
  // ещё списка; наполняется он отсюда, и запроса `/workspaces/personal` на
  // загрузке больше нет.
  const личное = тело.workspaces.find((ws) => ws.personal)
  if (личное) qc.setQueryData(keys.workspaces.personal, личное)
}

export async function fetchBootstrap(): Promise<Bootstrap | null> {
  try {
    return await unwrap<Bootstrap>(
      api.GET('/api/bootstrap', {
        params: { query: { notifications: СКОЛЬКО_В_КОЛОКОЛЬЧИКЕ } },
      }),
    )
  } catch (e) {
    if (isApiError(e) && e.status === 401) return null
    throw e
  }
}

export function useBootstrap(): UseQueryResult<Bootstrap | null> {
  const qc = useQueryClient()
  return useQuery({
    queryKey: keys.bootstrap,
    queryFn: async () => {
      const тело = await fetchBootstrap()
      if (тело) разложить(qc, тело)
      return тело
    },
    // Сводка нужна ровно один раз за загрузку страницы. Дальше каждая её часть
    // живёт своей жизнью: расход гасит конец задания, колокольчик — поток
    // человека. Перезапрашивать сводку целиком значило бы получать пять
    // ответов там, где изменился один.
    staleTime: Infinity,
    retry: false,
  })
}
