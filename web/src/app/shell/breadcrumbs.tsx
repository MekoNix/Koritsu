/* eslint-disable react-refresh/only-export-components --
 * Контекст, хуки и компонент крошек держатся в одном файле намеренно: они
 * бесполезны друг без друга, а разнесение по трём файлам ради горячей
 * перезагрузки этого одного модуля обошлось бы дороже, чем сама перезагрузка.
 */
/**
 * breadcrumbs — крошки «модуль / документ».
 *
 * Правка 2 макетов отменила иерархию «Проекты / … / Отчёт»: над модулем
 * ничего нет, и крошки состоят ровно из двух частей — модуль и открытый в нём
 * документ («Отчёты / Лабораторная 4»).
 *
 * Модуль оболочка знает сама, по адресу. Документ знает только экран, поэтому
 * он сообщает его хуком `useDocumentCrumb(name)`; ушёл экран — крошка
 * исчезает сама (это делает `useEffect` при размонтировании).
 *
 *     // внутри экрана области
 *     useDocumentCrumb(project?.name)
 */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

import { useT } from '@/i18n'

type CrumbCtx = {
  document: string | null
  setDocument: (name: string | null) => void
}

const Ctx = createContext<CrumbCtx | null>(null)

export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [document, setDocument] = useState<string | null>(null)
  const value = useMemo(() => ({ document, setDocument }), [document])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Назвать открытый документ. `undefined`/`null` — крошки документа нет. */
export function useDocumentCrumb(name: string | null | undefined): void {
  const ctx = useContext(Ctx)
  useEffect(() => {
    ctx?.setDocument(name ?? null)
    return () => ctx?.setDocument(null)
    // `ctx` стабилен по составу, зависимость — только имя.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name])
}

/** Ключ перевода модуля по адресу. Порядок важен: сначала длинные префиксы. */
const BY_PREFIX: [string, string][] = [
  ['/flowcharts', 'shell.page.flowcharts'],
  ['/uml', 'shell.page.uml'],
  ['/projects', 'shell.page.projects'],
  ['/reports', 'shell.page.reports'],
  ['/settings', 'shell.page.settings'],
  ['/admin', 'shell.page.admin'],
]

export function useCrumbs(): { module: string; document: string | null } {
  const t = useT()
  const { pathname } = useLocation()
  const ctx = useContext(Ctx)
  const hit = BY_PREFIX.find(([prefix]) => pathname.startsWith(prefix))
  return { module: t(hit ? hit[1] : 'shell.page.dashboard'), document: ctx?.document ?? null }
}

export function Breadcrumbs() {
  const { module, document } = useCrumbs()
  return (
    <nav className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap text-sm text-muted">
      <span className={document ? undefined : 'font-medium text-ink-strong'}>{module}</span>
      {document && (
        <>
          <span aria-hidden="true" className="opacity-50">
            /
          </span>
          <span className="truncate font-medium text-ink-strong">{document}</span>
        </>
      )}
    </nav>
  )
}
