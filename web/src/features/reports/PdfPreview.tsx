/**
 * PdfPreview — правая колонка: как отчёт выглядит в Word, и файлы для скачивания.
 *
 * Просмотрщик — встроенный, браузерный (`<embed>` на артефакт PDF), решение
 * владельца: pdf.js ради страницы, которую браузер и так умеет показывать, —
 * это мегабайт кода и свой набор ошибок отрисовки.
 *
 * **Превью по кнопке, а не само.** Сборка зовёт LibreOffice, стоит денег
 * (`price_build`) и занимает секунды; перерисовывать её на каждую правку тега
 * значило бы платить за каждое нажатие клавиши. Поэтому кнопка одна, и рядом с
 * ней сказано, что это стоит.
 *
 * DOCX и PDF собираются одним заданием (см. `useBuild`), поэтому «скачать Word»
 * не запускает вторую сборку — файл уже есть.
 */
import { useEffect, useState, type ReactNode } from 'react'

import { useT } from '@/i18n'
import { Button, EmptyState, Icon, Spinner } from '@/ui'

import type { BuildState } from './useBuild'

/**
 * Артефакт → адрес, который браузер согласится ПОКАЗАТЬ.
 *
 * Служба отдаёт артефакт с `Content-Disposition: attachment`
 * (`modules/artifacts.py`), и это правильно для кнопки «скачать»: файл без
 * имени и с чужим типом на своём домене — плохая мысль. Но `<embed>` на такой
 * адрес браузер не рисует, а скачивает: заголовок сильнее тега.
 *
 * Поэтому байты берутся `fetch`'ем (cookie сессии уезжает сама, origin тот же)
 * и показываются как `blob:` — у него никакого расположения нет, и встроенный
 * просмотрщик работает как ни в чём не бывало. Ссылку обязательно отпускаем:
 * каждый `createObjectURL` держит копию файла в памяти вкладки до перезагрузки
 * страницы.
 *
 * Второй путь — параметр `?inline` в службе — тоже годится, но он меняет чужой
 * маршрут, которым пользуются и схемы, и выгрузка; предложено главной сессии
 * отдельно.
 */
function useInlinePdf(url: string | null): { src: string | null; failed: boolean } {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!url) {
      setSrc(null)
      setFailed(false)
      return
    }
    let живо = true
    let ссылка: string | null = null
    setFailed(false)
    void fetch(url, { credentials: 'include' })
      .then((ответ) => (ответ.ok ? ответ.blob() : Promise.reject(new Error(String(ответ.status)))))
      .then((байты) => {
        if (!живо) return
        ссылка = URL.createObjectURL(байты)
        setSrc(ссылка)
      })
      .catch(() => {
        if (живо) setFailed(true)
      })
    return () => {
      живо = false
      if (ссылка) URL.revokeObjectURL(ссылка)
    }
  }, [url])

  return { src, failed }
}

export function PdfPreview({
  build,
  priceHint,
  canBuild,
}: {
  build: BuildState
  priceHint: ReactNode
  canBuild: boolean
}) {
  const t = useT()
  const превью = useInlinePdf(build.pdfUrl)

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
        {build.running || (build.pdfUrl && !превью.src && !превью.failed) ? (
          <div className="flex h-full flex-col items-center justify-center gap-s3 text-sm text-muted">
            <Spinner size={28} />
            {t('reports.pdf.building')}
          </div>
        ) : build.error || превью.failed ? (
          <div className="flex h-full flex-col items-center justify-center gap-s3 p-s5 text-center">
            <Icon name="error" size={32} className="text-err" />
            <p className="max-w-[40ch] text-sm text-ink">
              {build.error ?? t('reports.pdf.embedFailed')}
            </p>
            <Button variant="primary" size="sm" onClick={build.start} disabled={!canBuild}>
              {t('common.action.retry')}
            </Button>
          </div>
        ) : превью.src ? (
          <embed
            key={превью.src}
            src={превью.src}
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
              <div className="flex flex-col items-center gap-s2">
                <Button variant="primary" size="sm" onClick={build.start} disabled={!canBuild}>
                  {t('reports.pdf.build')}
                </Button>
                <span className="text-xs text-muted">{priceHint}</span>
              </div>
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
