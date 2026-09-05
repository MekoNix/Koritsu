/**
 * ExportDialog — «Скачать работу»: выбор формата, задание, файл.
 *
 * Правило: экспорт — кнопка в проекте, задание, скачивание из уведомления.
 * Все три части здесь и ровно в этом порядке.
 *
 * **Цены и остатка здесь нет** (то же правило, что у прогонов модели): цена
 * зависит от того, сколько выйдет работы, и названное до нажатия число было бы
 * обещанием, которого никто не давал. Расход человек смотрит одним местом —
 * «Расход и лимиты» в настройках.
 *
 * **После постановки окно не закрывается само.** Задание уехало в очередь, и
 * закрытое окно оставило бы человека гадать, случилось ли что-нибудь. Вместо
 * этого окно показывает ход работы и — когда файл готов — кнопку скачивания.
 * Закрыл окно раньше времени, ушёл на другой экран, закрыл вкладку: та же
 * ссылка придёт в колокольчик (`data.artifacts`), она и есть главный путь.
 *
 * **Тоста на завершение здесь нет** — его показывает оболочка по уведомлению
 * (один тост на одно событие). Свой тост остался только на отказ постановки,
 * то есть на обычный запрос, а не на задание.
 */
import { useEffect, useState } from 'react'

import { errorText } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, Dialog, Icon, Segmented, Spinner, type SegmentedOption } from '@/ui'

import { artifactUrl, useEnqueueJob } from './data'
import { BUILD, EXPORT, jobArtifacts, формат, useExportProject, type ExportFormat } from './export'

export function ExportDialog({
  projectId,
  open,
  onOpenChange,
  /** Есть ли у проекта шаблон: без него Word и PDF собирать не из чего. */
  hasTemplate,
}: {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  hasTemplate: boolean
}) {
  const t = useT()
  const enqueue = useEnqueueJob()
  const выгрузка = useExportProject()

  // Проект без шаблона умеет только архив — им и открываемся, чтобы человек не
  // упирался в отключённую кнопку на первом же экране.
  const [format, setFormat] = useState<ExportFormat>(hasTemplate ? 'document' : 'archive')
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const stream = useJobStream(jobId)

  // Новое открытие — чистое окно: ссылка на прошлый архив рядом с новым
  // выбором формата читалась бы как «вот ваш файл», хотя файл тот, прежний.
  useEffect(() => {
    if (!open) {
      setJobId(null)
      setError(null)
    }
  }, [open])

  const выбран = формат(format)
  const нельзя = выбран.needsTemplate && !hasTemplate
  const ставится = enqueue.isPending || выгрузка.isPending
  const идёт = !!jobId && !stream.done

  const файлы = stream.done && stream.job?.status === 'done' ? jobArtifacts(stream.job.result) : {}
  const готово = Object.entries(файлы)
  const провал = stream.done && stream.job?.status !== 'done'

  // Пунктов два, по заданию на пункт: «Word» и «PDF» отдельными строками были
  // выбором без разницы — за обоими стоял один прогон `build` и одна цена.
  const options: SegmentedOption<ExportFormat>[] = [
    { value: 'document', label: t('projects.export.format.document'), icon: 'file' },
    { value: 'archive', label: t('projects.export.format.archive'), icon: 'folder' },
  ]

  function запустить() {
    setError(null)
    const принять = (задание: { id: string }) => setJobId(задание.id)
    const отказ = (беда: unknown) => setError(errorText(беда))
    if (выбран.job === EXPORT) {
      выгрузка.mutate(projectId, { onSuccess: принять, onError: отказ })
    } else {
      // Пара DOCX+PDF одним прогоном: PDF получается из собранного DOCX тем же
      // вызовом LibreOffice, и второй прогон стоил бы второй цены за тот же
      // документ (`useBuild`). Поэтому и пункт в списке один.
      enqueue.mutate(
        { kind: BUILD, projectId, payload: { outputs: ['docx', 'pdf'] } },
        { onSuccess: принять, onError: отказ },
      )
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('projects.export.title')}
      description={t('projects.export.description')}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('common.action.close')}
          </Button>
          <Button
            variant="primary"
            disabled={нельзя || идёт}
            loading={ставится}
            onClick={запустить}
          >
            <Icon name="download" size={16} />
            {jobId ? t('projects.export.again') : t('projects.export.start')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-s3 text-sm">
        <Segmented
          value={format}
          options={options}
          onChange={setFormat}
          label={t('projects.export.formatLabel')}
        />

        <p className="text-xs text-muted">{t(`projects.export.hint.${format}`)}</p>

        {нельзя && <p className="text-xs text-warn">{t('projects.export.noTemplate')}</p>}

        {error && <p className="text-xs text-err">{error}</p>}

        {идёт && (
          <p className="flex items-center gap-s2 rounded-md border border-line bg-surface-2 px-s3 py-s2 text-xs text-muted">
            <Spinner size={14} />
            {t('projects.export.running')}
          </p>
        )}

        {провал && (
          <p className="rounded-md border border-line bg-err-bg px-s3 py-s2 text-xs text-err">
            {t('projects.export.failed')}
          </p>
        )}

        {готово.length > 0 && (
          <div className="flex flex-col gap-s2 rounded-md border border-line bg-surface-2 p-s3">
            <p className="text-xs text-muted">{t('projects.export.ready')}</p>
            <div className="flex flex-wrap gap-s2">
              {готово.map(([вид, art]) => (
                <Button key={вид} variant="secondary" size="sm" asChild>
                  <a href={artifactUrl(projectId, art)} download>
                    <Icon name="download" size={14} />
                    {t(`projects.export.file.${вид}`)}
                  </a>
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>
    </Dialog>
  )
}
