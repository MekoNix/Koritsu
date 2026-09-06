/**
 * WordToPdfWidget — быстрая утилита «Word → PDF» в одно действие.
 *
 * **Почему через проект.** Отдельного маршрута «переверни мне этот файл в PDF»
 * у службы нет и не будет: собирает документ задание `build`, а оно работает в
 * проекте — там лежит шаблон, значения и хранилище артефактов. Поэтому плитка
 * делает ровно то, что сделал бы человек руками, только без экранов: заводит
 * работу с брошенным DOCX как шаблоном, ставит `build` и отдаёт собранный PDF.
 * Работа остаётся в списке — это не мусор, а тот же файл, к которому можно
 * вернуться; ссылка на неё показывается рядом с готовым PDF.
 *
 * Тоста на конец здесь нет: завершение фоновой задачи тостит оболочка
 * (`useUserEvents`), и второй был бы дублем. Свой тост — только на отказ.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useJobStream } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, Icon, Spinner, useToast } from '@/ui'
import { FileDrop } from '@/features/projects/FileDrop'
import { useCurrentWorkspace } from '@/api/hooks'
import { BUILD, artifactUrl, useCreateProject, useEnqueueJob } from '@/features/projects/data'

import { Widget } from './Widget'

const DOCX = '.docx,.dotx,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

/** Что уже сделано: проект заведён, задание поставлено. */
type Работа = { projectId: string; jobId: string; name: string }

/** Идентификатор собранного PDF из результата задания `build`. */
function pdfArtifact(result: unknown): string | undefined {
  const artifacts = (result as { artifacts?: Record<string, unknown> } | null)?.artifacts
  const pdf = artifacts?.pdf
  return typeof pdf === 'string' && pdf ? pdf : undefined
}

export function WordToPdfWidget() {
  const t = useT()
  const toast = useToast()
  const workspace = useCurrentWorkspace()
  const create = useCreateProject()
  const enqueue = useEnqueueJob()
  const [работа, setРаботу] = useState<Работа | null>(null)

  const { job } = useJobStream(работа?.jobId ?? null)
  const artifact = job?.status === 'done' ? pdfArtifact(job.result) : undefined
  const failed = job?.status === 'failed' || job?.status === 'cancelled'
  const busy = create.isPending || enqueue.isPending || (!!работа && !job?.status)
  const running = !!работа && (job?.status === 'queued' || job?.status === 'running')

  const start = async (file: File) => {
    const workspaceId = workspace.data?.id
    if (!workspaceId) return
    // Имя работы — имя файла без расширения: человек узнает её в списке.
    const name = file.name.replace(/\.[^.]+$/, '') || file.name
    try {
      const project = await create.mutateAsync({ workspaceId, name, template: file })
      const job = await enqueue.mutateAsync({
        kind: BUILD,
        projectId: project.id,
        payload: { outputs: ['docx', 'pdf'] },
      })
      setРаботу({ projectId: project.id, jobId: job.id, name })
    } catch (error) {
      toast.fail(error, t('dashboard.wordToPdf.failed'))
    }
  }

  return (
    <Widget>
      <div className="flex h-full flex-col gap-s2">
        <div className="flex items-center gap-s2">
          <Icon name="file" size={18} className="text-muted" />
          <h2 className="flex-1 truncate font-display text-md font-semibold text-ink-strong">
            {t('dashboard.wordToPdf.title')}
          </h2>
        </div>

        {artifact && работа ? (
          <div className="flex flex-1 flex-col justify-center gap-s2">
            <p className="truncate text-sm text-ink" title={работа.name}>
              {работа.name}
            </p>
            <Button variant="primary" size="sm" asChild>
              <a href={artifactUrl(работа.projectId, artifact)} download>
                <Icon name="download" size={16} />
                {t('dashboard.wordToPdf.download')}
              </a>
            </Button>
            <div className="flex items-center justify-between gap-s2 text-xs">
              <Link to={`/projects/${работа.projectId}`} className="text-accent hover:underline">
                {t('dashboard.wordToPdf.openProject')}
              </Link>
              <button
                type="button"
                className="text-muted hover:text-ink"
                onClick={() => setРаботу(null)}
              >
                {t('dashboard.wordToPdf.again')}
              </button>
            </div>
          </div>
        ) : failed && работа ? (
          <div className="flex flex-1 flex-col justify-center gap-s2 text-center">
            <p className="text-sm text-err">{t('dashboard.wordToPdf.failed')}</p>
            <Link
              to={`/projects/${работа.projectId}`}
              className="text-xs text-accent hover:underline"
            >
              {t('dashboard.wordToPdf.openProject')}
            </Link>
            <Button variant="ghost" size="sm" onClick={() => setРаботу(null)}>
              {t('dashboard.wordToPdf.again')}
            </Button>
          </div>
        ) : busy || running ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-s2 text-center">
            <Spinner />
            <p className="text-xs text-muted">
              {running ? t('dashboard.wordToPdf.building') : t('dashboard.wordToPdf.sending')}
            </p>
          </div>
        ) : (
          <FileDrop
            compact
            accept={DOCX}
            disabled={!workspace.data}
            className="flex-1"
            label={t('dashboard.wordToPdf.drop')}
            hint={t('dashboard.wordToPdf.dropHint')}
            onFiles={(files) => {
              const file = files[0]
              if (file) void start(file)
            }}
          />
        )}
      </div>
    </Widget>
  )
}
