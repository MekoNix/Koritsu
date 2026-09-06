/* eslint-disable react-refresh/only-export-components --
 * Хук `useWorkspaceName` и два компонента держатся в одном файле намеренно:
 * они об одном — как пространство называется на экране и что делать, когда
 * открыто чужое. Разнести их значило бы завести файл ради одной строки.
 */
/**
 * WorkspaceCaption — «в каком пространстве лежит то, что я смотрю».
 *
 * Пространство заводят ради разделения (своё отдельно, кафедра отдельно), и
 * разделение это ничего не стоит, пока человек не видит, где он находится.
 * Переключатель в сайдбаре отвечает на вопрос «где я вообще», но работа
 * открывается и по ссылке — из письма, из закладки, — и тогда она может лежать
 * в соседнем пространстве, а сайдбар всё ещё показывает прежнее. Поэтому имя
 * пространства стоит подписью там, где выбирают работу: на списке работ, на
 * карточке работы, на главных модулей.
 *
 * `OtherWorkspaceNotice` — второй случай того же: работа открыта, но лежит не в
 * текущем пространстве. Молчать здесь нельзя (человек будет искать её в списке
 * и не найдёт), запрещать — тоже (ссылка законная), поэтому показывается
 * полоска с кнопкой «Переключить пространство»: одно нажатие — и списки вокруг
 * становятся про то же пространство, что и открытая работа.
 */
import { Link } from 'react-router-dom'

import { setCurrentWorkspaceId, useCurrentWorkspace } from '@/api/hooks'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon } from '@/ui'

import { workspaceLabel } from './types'
import { usePersonalName } from './usePersonalName'

/** Столько знает подпись о пространстве: имени и «личное ли» ей хватает. */
export type NamedWorkspace = { id?: string; name: string; personal: boolean }

/**
 * Как пространство зовётся на экране. Без аргумента — текущее.
 *
 * Личное пространство служба зовёт `<ник>-workspace` (а строки постарше —
 * `Personal`), и показывать это слово человеку незачем: его называет
 * `workspaceLabel` вместе с `usePersonalName`, одинаково во всех четырёх
 * местах, где имя пространства видно.
 */
export function useWorkspaceName(ws?: NamedWorkspace | null): string {
  const текущее = useCurrentWorkspace()
  const личное = usePersonalName()
  const карточка = ws ?? текущее.data
  return карточка ? workspaceLabel(карточка, личное) : ''
}

/**
 * Подпись «Пространство · <имя>».
 *
 * Имени ещё нет (карточка едет) — подписи нет вовсе: пустая строка на её месте
 * читается как сломанный экран, а скелетон ради двух слов дороже самой подписи.
 */
export function WorkspaceCaption({
  ws,
  className,
}: {
  ws?: NamedWorkspace | null
  className?: string
}) {
  const t = useT()
  const имя = useWorkspaceName(ws)
  if (!имя) return null
  return (
    <p className={cn('flex min-w-0 items-center gap-1.5 text-xs text-muted', className)}>
      <Icon name="users" size={14} className="shrink-0" />
      <span className="uppercase tracking-wider">{t('workspace.switcher.caption')}</span>
      <span className="min-w-0 truncate font-medium text-ink">{имя}</span>
    </p>
  )
}

/**
 * Полоска «эта работа — из другого пространства» с кнопкой переключения.
 *
 * Показывается только когда пространство работы известно и не совпадает с
 * текущим. Сравнение идёт по идентификатору, а не по имени: имена пространств
 * человек назначает сам, и два «Кафедры» — обычное дело.
 *
 * Личное пространство в памяти сайта записано как `null`
 * (`useCurrentWorkspaceId`), поэтому «текущее» берётся из карточки, а не из
 * сохранённого выбора: иначе своя же работа в личном пространстве считалась бы
 * чужой при каждой загрузке страницы.
 */
export function OtherWorkspaceNotice({ ws }: { ws?: NamedWorkspace | null }) {
  const t = useT()
  const текущее = useCurrentWorkspace()
  const имя = useWorkspaceName(ws)

  const идентификатор = ws?.id
  const чужое = !!идентификатор && !!текущее.data && текущее.data.id !== идентификатор
  if (!чужое) return null

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-s3 rounded-md border border-line bg-surface-2 px-s4 py-s3 text-sm"
    >
      <Icon name="users" size={16} className="shrink-0 text-muted" />
      <p className="min-w-0 flex-1 text-ink">
        {t('workspace.other.text', { name: имя })}{' '}
        <span className="text-muted">{t('workspace.other.hint')}</span>
      </p>
      <div className="flex items-center gap-s2">
        <Button
          variant="primary"
          size="sm"
          onClick={() => setCurrentWorkspaceId(ws?.personal ? null : (идентификатор ?? null))}
        >
          <Icon name="restore" size={16} />
          {t('workspace.other.switch')}
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/projects">{t('common.error.toProjects')}</Link>
        </Button>
      </div>
    </div>
  )
}
