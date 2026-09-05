/**
 * PdfPreview — правая колонка: как отчёт выглядит в Word, и файлы для скачивания.
 *
 * Просмотрщик — встроенный, браузерный (`<embed>` на артефакт PDF):
 * pdf.js ради страницы, которую браузер и так умеет показывать, —
 * это мегабайт кода и свой набор ошибок отрисовки.
 *
 * **Адрес прямой, без `blob:`**. Раньше служба отдавала артефакт
 * только вложением (`Content-Disposition: attachment`), а заголовок сильнее
 * тега: `<embed>` на такой адрес браузер не рисует, а скачивает. Обходили это
 * выкачиванием байтов `fetch`'ем и показом через `URL.createObjectURL` — то
 * есть вторым запросом за тем же файлом и копией отчёта в памяти вкладки до
 * перезагрузки страницы. Теперь у службы есть `?inline=1`, и просмотрщику
 * достаётся тот самый адрес: ни второго запроса, ни копии, ни
 * `revokeObjectURL`, который однажды забудут.
 *
 * Ссылки «скачать» ведут по тому же адресу **без** параметра: там нужно ровно
 * обратное — файл в папке «Загрузки», с именем.
 *
 * **Превью по кнопке, а не само.** Сборка зовёт LibreOffice, стоит денег
 * (`price_build`) и занимает секунды; перерисовывать её на каждую правку тега
 * значило бы платить за каждое нажатие клавиши. Поэтому кнопка одна и нажимает
 * её человек.
 *
 * DOCX и PDF собираются одним заданием (см. `useBuild`), поэтому «скачать Word»
 * не запускает вторую сборку — файл уже есть.
 */
import { useT } from '@/i18n'
import { Button, EmptyState, Icon, Spinner } from '@/ui'

import type { BuildState } from './useBuild'

export function PdfPreview({ build, canBuild }: { build: BuildState; canBuild: boolean }) {
  const t = useT()

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-2">
      <div className="flex flex-wrap items-center gap-s2 border-b border-line bg-surface px-s3 py-s2">
        <span className="text-sm font-semibold text-ink-strong">{t('reports.pdf.title')}</span>
        <Button
          variant="secondary"
          size="sm"
          disabled={!canBuild || build.running}
          onClick={build.start}
        >
          {build.running ? <Spinner size={14} /> : <Icon name="refresh" size={14} />}
          {build.pdfUrl ? t('reports.pdf.rebuild') : t('reports.pdf.build')}
        </Button>
        <span className="ml-auto flex items-center gap-s2">
          {build.docxUrl && (
            <Button variant="ghost" size="sm" asChild>
              <a href={build.docxUrl} download>
                {t('reports.pdf.downloadDocx')}
              </a>
            </Button>
          )}
          {build.pdfUrl && (
            <Button variant="ghost" size="sm" asChild>
              <a href={build.pdfUrl} download>
                {t('reports.pdf.downloadPdf')}
              </a>
            </Button>
          )}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {build.running ? (
          <div className="flex h-full flex-col items-center justify-center gap-s3 text-sm text-muted">
            <Spinner size={28} />
            {t('reports.pdf.building')}
          </div>
        ) : build.error ? (
          <div className="flex h-full flex-col items-center justify-center gap-s3 p-s5 text-center">
            <Icon name="error" size={32} className="text-err" />
            <p className="max-w-[40ch] text-sm text-ink">{build.error}</p>
            <Button variant="primary" size="sm" onClick={build.start} disabled={!canBuild}>
              {t('common.action.retry')}
            </Button>
          </div>
        ) : build.pdfInlineUrl ? (
          <embed
            key={build.pdfInlineUrl}
            src={build.pdfInlineUrl}
            type="application/pdf"
            title={t('reports.pdf.title')}
            className="h-full w-full"
          />
        ) : (
          <EmptyState
            icon="file"
            title={t('reports.pdf.emptyTitle')}
            text={t('reports.pdf.emptyText')}
            action={
              <Button variant="primary" size="sm" onClick={build.start} disabled={!canBuild}>
                {t('reports.pdf.build')}
              </Button>
            }
          />
        )}
      </div>

      {build.unfilled.length > 0 && (
        <p className="border-t border-line bg-warn-bg px-s3 py-s2 text-xs text-ink">
          {t('reports.pdf.unfilled', {
            n: build.unfilled.length,
            keys: build.unfilled.slice(0, 5).join(', '),
          })}
        </p>
      )}
    </div>
  )
}
