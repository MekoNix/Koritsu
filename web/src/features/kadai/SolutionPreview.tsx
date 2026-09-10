/**
 * SolutionPreview — «как будет в Word»: оглавление, страница и замечание.
 *
 * Три вещи стоят сверху вниз в том порядке, в каком с работой разговаривают:
 * оглавление блоков (какой раздел смотрим), сама вёрстка и форма замечания к
 * выбранному блоку. Список карточек с содержимым блоков рядом с этим не нужен:
 * содержимое показывает вёрстка, и второй его показ означал бы чтение работы
 * дважды в двух разных видах.
 *
 *     Просмотрщик — браузерный
 *     ------------------------
 *
 * `<embed>` на артефакт PDF, как и у отчётов (`reports/PdfPreview`). Свой
 * просмотрщик на pdf.js давал области блоков прямо на странице, но платой за
 * них была чужая отрисовка: шрифты, формулы и поля рисует не тот движок,
 * которым документ будут открывать, — а превью нужно ровно затем, чтобы
 * увидеть настоящую вёрстку. Плюс два мегабайта кода на экран, который браузер
 * рисует сам.
 *
 * Отсюда же нет кнопок масштаба: у встроенного просмотрщика он свой, со своими
 * привычными сочетаниями клавиш, и вторая пара кнопок рядом управляла бы не тем
 * масштабом, который человек видит.
 *
 *     Как попадают в блок
 *     -------------------
 *
 * При сборке на первый абзац каждого блока ставится закладка, и в PDF она
 * выходит именованным назначением (`pdfBlocks.bookmarkName`). Выбор в
 * оглавлении меняет у адреса только фрагмент — `#nameddest=<имя>`, — и
 * просмотрщик прокручивается к разделу; сам документ при этом тот же самый и
 * приезжает из кэша.
 *
 *     Высоту задаёт человек
 *     ---------------------
 *
 * Рамка тянется за нижний край (`resize: vertical`) и помнит свою высоту между
 * заходами. Одной высоты на всех не бывает: страница A4 на ноутбуке и на
 * широком мониторе — это разные доли экрана, а смотрят в эту рамку подолгу.
 * Ниже 60vh рамка не сжимается: в меньшей видно кусок страницы, а по куску не
 * проверить ни полей, ни переносов — того, ради чего превью и открывают.
 */
import { useEffect, useMemo, useRef } from 'react'
import type { ReactNode } from 'react'

import { useT } from '@/i18n'
import { Button, EmptyState, Icon, Spinner } from '@/ui'
import type { BuildState } from '@/features/reports/useBuild'

import { BlockPicker, ReworkForm, type ReworkRequest } from './BlockPicker'
import { bookmarkName } from './pdfBlocks'
import type { BlockRecordBody } from './types'

/**
 * Где помнится высота рамки. Ключ с приставкой: `localStorage` один на весь
 * домен. Высота — свойство глаза и монитора, а не решения, поэтому ключ один на
 * все решения: заводить её каждой задаче заново значило бы настраивать рамку
 * при каждом новом задании.
 */
const КЛЮЧ_ВЫСОТЫ = 'koritsu.kadai.previewHeight'

/** Пределы запомненной высоты: за ними это уже не рамка, а ошибка записи. */
const МИН_ВЫСОТА = 240
const МАКС_ВЫСОТА = 4000

/** Сколько ждать после последнего движения края, прежде чем записать высоту. */
const ЗАДЕРЖКА = 400

function прочитать_высоту(): number | null {
  try {
    const сырое = window.localStorage.getItem(КЛЮЧ_ВЫСОТЫ)
    const число = сырое ? Number(сырое) : NaN
    if (!Number.isFinite(число) || число < МИН_ВЫСОТА || число > МАКС_ВЫСОТА) return null
    return Math.round(число)
  } catch {
    // Приватное окно или запрет на хранилище: рамка просто открывается в свою
    // высоту по умолчанию. Тянуть её за край это не мешает.
    return null
  }
}

function записать_высоту(высота: number): void {
  try {
    window.localStorage.setItem(КЛЮЧ_ВЫСОТЫ, String(Math.round(высота)))
  } catch {
    // См. `прочитать_высоту`: без хранилища высота живёт до перезагрузки.
  }
}

export function SolutionPreview({
  build,
  canBuild,
  extra,
  blocks,
  loading,
  selected,
  onSelect,
  onRework,
  disabled,
}: {
  build: BuildState
  canBuild: boolean
  /** Добавочная кнопка в шапке: у решений это «развернуть на всю ширину». */
  extra?: ReactNode
  blocks: BlockRecordBody[] | undefined
  /** Блоки ещё едут с тома. */
  loading: boolean
  /** Выбранный блок: к нему ведёт вёрстка и к нему пишется замечание. */
  selected: string | null
  onSelect: (ключ: string | null) => void
  onRework: (запрос: ReworkRequest) => void
  /** Идёт прогон: форма замечания заблокирована. */
  disabled: boolean
}) {
  const t = useT()

  const рамка = useRef<HTMLDivElement>(null)
  // Высота читается один раз, при заведении рамки, и в состоянии не живёт:
  // тянет край браузер, он же и пишет `style.height` узлу, а перерисовка на
  // каждый пиксель движения края означала бы перерисовку страницы вёрстки.
  const своя_высота = useRef<number | null>(прочитать_высоту())

  useEffect(() => {
    const узел = рамка.current
    if (!узел) return
    let таймер: ReturnType<typeof setTimeout> | undefined
    // `offsetHeight`, а не `contentRect`: рамка меряется по внешнему краю
    // (`box-sizing: border-box`), и записанная высота содержимого укорачивала бы
    // её на толщину рамки при каждом заходе.
    const наблюдатель = new ResizeObserver(() => {
      clearTimeout(таймер)
      таймер = setTimeout(() => записать_высоту(узел.offsetHeight), ЗАДЕРЖКА)
    })
    наблюдатель.observe(узел)
    return () => {
      clearTimeout(таймер)
      наблюдатель.disconnect()
    }
  }, [])

  const по_ключу = useMemo(() => new Map((blocks ?? []).map((блок) => [блок.key, блок])), [blocks])
  const выбранный = selected ? по_ключу.get(selected) : undefined

  // Меняется у адреса только фрагмент: документ тот же, и просмотрщику остаётся
  // прокрутиться к названному месту.
  const адрес =
    build.pdfInlineUrl && selected
      ? `${build.pdfInlineUrl}#nameddest=${bookmarkName(selected)}`
      : build.pdfInlineUrl

  return (
    <div className="flex flex-col gap-s2">
      <div className="flex flex-wrap items-center gap-s2 rounded-md border border-line bg-surface px-s3 py-s2">
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
          {extra}
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

      {/* Оглавление над страницей, а не сбоку: выбор блока — это движение по
          документу, и список, из которого его делают, стоит там же, где стоит
          оглавление в самом документе. */}
      <BlockPicker blocks={blocks} loading={loading} selected={selected} onSelect={onSelect} />
      {адрес && (blocks ?? []).length > 0 && (
        <p className="text-xs text-muted">{t('kadai.preview.pickHint')}</p>
      )}

      {/* Нижняя полоса рамки пустая намеренно: уголок, за который её тянут,
          рисует браузер в правом нижнем углу самой рамки, и страница
          просмотрщика, растянутая до края, забрала бы нажатие себе. */}
      <div
        ref={рамка}
        style={{ height: своя_высота.current ?? undefined }}
        className="flex min-h-[60vh] resize-y flex-col overflow-hidden rounded-md border border-line bg-surface-2 pb-s3"
      >
        <div className="min-h-0 flex-1">
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
          ) : адрес ? (
            // Ключ по адресу артефакта, а не по всему адресу с фрагментом:
            // смена выбранного блока меняет только фрагмент, и пересоздавать
            // из-за неё просмотрщик значило бы выкачивать документ на каждый
            // щелчок по оглавлению.
            <embed
              key={build.pdfInlineUrl ?? ''}
              src={адрес}
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
      </div>

      {build.unfilled.length > 0 && (
        <p className="rounded-md border border-line bg-warn-bg px-s3 py-s2 text-xs text-ink">
          {t('reports.pdf.unfilled', {
            n: build.unfilled.length,
            keys: build.unfilled.slice(0, 5).join(', '),
          })}
        </p>
      )}

      {/* Форма замечания под страницей: сказать «здесь не то» человек хочет
          сразу после того, как это «не то» увидел, — а не пролистав экран
          обратно к списку. */}
      {выбранный ? (
        <ReworkForm block={выбранный} disabled={disabled} onRework={onRework} />
      ) : (
        (blocks ?? []).length > 0 && (
          <p className="rounded-md border border-line bg-surface-2 px-s3 py-s2 text-xs text-muted">
            {t('kadai.blocks.pickFirst')}
          </p>
        )
      )}
    </div>
  )
}
