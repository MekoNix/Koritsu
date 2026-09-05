/**
 * PageStub — заглушка страницы области.
 *
 * Нужна ровно на одну ночь: каркас обязан собираться и открываться по всем
 * маршрутам до того, как области наполнят содержимым. Каждая заглушка лежит в
 * своём файле области (`features/<область>/…`), и агент этой области заменяет
 * содержимое файла, не трогая ни роутер, ни соседей.
 *
 * Убрать этот компонент можно будет, когда последняя область его перестанет
 * звать.
 */
import type { ReactNode } from 'react'

import { useT } from '@/i18n'

export function PageStub({ title, children }: { title: string; children?: ReactNode }) {
  const t = useT()
  return (
    <section className="flex flex-col gap-s3">
      <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">{title}</h1>
      {children ?? <p className="text-sm text-muted">{t('shell.page.placeholder')}</p>}
    </section>
  )
}
