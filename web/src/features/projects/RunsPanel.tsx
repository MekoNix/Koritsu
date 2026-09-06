/**
 * RunsPanel — журнал запусков работы: что в ней делали, когда и как это зовут.
 *
 * Заменяет собой вопрос «куда можно пойти», на который отвечали плитки модулей.
 * На работе с двумя схемами такой ответ бесполезен: человек ищет не модуль, а
 * ту схему, которую он вчера сделал. Здесь список: модуль, имя, время, — и
 * сортировка, потому что список растёт.
 *
 * **Имя рисует сайт, а не служба.** Служба хранит имя, которое человек дал
 * запуску, и порядковый номер (`n`); имя по умолчанию — русское слово, а наружу
 * служба говорит по-английски. Поэтому «Схема 2 — Курсовая» собирается здесь,
 * из `module`, `n` и имени работы.
 *
 * **Отчёт и решение заводятся отсюда.** Они создаются отдельно и привязываются к
 * текущей работе: кнопка ставит запись в журнал и уводит на экран модуля. Схемы
 * так не заводятся — схема появляется, когда её построили, и записывает её сам
 * модуль схем.
 *
 * Удаление убирает **запись**, а не файл: артефакт адресуется содержимым и может
 * стоять значением тега, а снести его вслед за строкой значило бы выбить
 * картинку из готового документа (`packages/api/projects/runs.py`).
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useT } from '@/i18n'
import { Button, EmptyState, ErrorState, Icon, Select, Skeleton, useToast } from '@/ui'

import { Panel } from './Panel'
import { RunName } from './RunName'
import { useCreateProjectRun, useDeleteProjectRun, useProjectRuns } from './data'
import { formatWhen, runTitle } from './format'
import { projectModuleLink } from './moduleRoutes'
import type { ProjectRun, RunSort } from './types'

/** Порядки, которые понимает служба (`sort` у `GET …/runs`). */
const ПОРЯДКИ: RunSort[] = ['new', 'old', 'name', 'module']

/** Модули, работу с которыми заводят прямо из карточки. */
const ЗАВОДЯТСЯ = ['reports', 'kadai'] as const

export function RunsPanel({
  projectId,
  projectName,
  canEdit,
}: {
  projectId: string
  projectName: string
  canEdit: boolean
}) {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const [sort, setSort] = useState<RunSort>('new')

  const runs = useProjectRuns(projectId, sort)
  const create = useCreateProjectRun()
  const remove = useDeleteProjectRun()

  function завести(module: string) {
    create.mutate(
      { projectId, module },
      {
        onSuccess: () => {
          const link = projectModuleLink(module)
          if (link) navigate(link.href(projectId))
        },
        onError: (e) => toast.fail(e),
      },
    )
  }

  const действия = canEdit ? (
    <>
      {ЗАВОДЯТСЯ.map((module) => (
        <Button
          key={module}
          variant="secondary"
          loading={create.isPending && create.variables?.module === module}
          onClick={() => завести(module)}
        >
          <Icon name="plus" size={16} />
          {t(`projects.runs.create.${module}`)}
        </Button>
      ))}
    </>
  ) : null

  return (
    <Panel title={t('projects.runs.title')} action={действия}>
      {runs.isPending ? (
        <div className="flex flex-col gap-s2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 rounded-sm" />
          ))}
        </div>
      ) : runs.error ? (
        <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
      ) : (runs.data ?? []).length === 0 ? (
        <EmptyState compact title={t('projects.runs.empty')} text={t('projects.runs.emptyHint')} />
      ) : (
        <>
          {/* Сортировка стоит над списком, а не в шапке панели: в шапке уже
              две кнопки, и выпадающий список рядом с ними читался бы как
              третье действие. */}
          <div className="mb-s3 flex justify-end">
            <Select
              aria-label={t('projects.runs.sort.label')}
              value={sort}
              className="w-auto"
              onChange={(e) => setSort(e.target.value as RunSort)}
            >
              {ПОРЯДКИ.map((порядок) => (
                <option key={порядок} value={порядок}>
                  {t(`projects.runs.sort.${порядок}`)}
                </option>
              ))}
            </Select>
          </div>

          <ul className="flex flex-col gap-s2">
            {(runs.data ?? []).map((run) => (
              <RunRow
                key={run.id}
                run={run}
                projectId={projectId}
                title={runTitle(t, run, projectName)}
                canEdit={canEdit}
                onRemove={() =>
                  remove.mutate({ projectId, runId: run.id }, { onError: (e) => toast.fail(e) })
                }
              />
            ))}
          </ul>
        </>
      )}
    </Panel>
  )
}

function RunRow({
  run,
  projectId,
  title,
  canEdit,
  onRemove,
}: {
  run: ProjectRun
  projectId: string
  title: string
  canEdit: boolean
  onRemove: () => void
}) {
  const t = useT()
  const link = projectModuleLink(run.module)

  return (
    <li className="flex items-center gap-s3 rounded-sm border border-line bg-surface-2 px-s3 py-s2">
      {/* Ссылкой стало само имя, а не вся строка: рядом с ним теперь поле
          правки, а поле внутри ссылки открывало бы её от каждого щелчка.
          Модуля без экрана работы в журнале быть не должно, но список приходит
          из базы, а не из таблицы адресов, — и ссылка в никуда хуже имени без
          ссылки. */}
      {link && (
        <Icon
          name={link.icon}
          size={18}
          style={{ color: `var(${link.colorVar})` }}
          className="shrink-0"
        />
      )}
      <span className="min-w-0 flex-1">
        <RunName
          projectId={projectId}
          runId={run.id}
          name={run.name}
          title={title}
          canEdit={canEdit}
          href={link ? (link.runHref?.(projectId, run.id) ?? link.href(projectId)) : undefined}
          className="text-sm font-medium text-ink-strong"
          iconSize={14}
        />
        <span className="block truncate text-xs text-muted">
          {t(`shell.nav.${run.module}`)}
          {' · '}
          {formatWhen(run.created_at)}
        </span>
      </span>
      {canEdit && (
        <Button
          variant="ghost"
          size="sm"
          aria-label={t('projects.runs.remove', { name: title })}
          onClick={onRemove}
        >
          <Icon name="trash" size={16} />
        </Button>
      )}
    </li>
  )
}
