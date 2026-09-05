/**
 * ConditionStep — первый шаг работы: «условие распознано, всё верно?».
 *
 * Отдельный шаг с двумя кнопками стоит здесь намеренно.
 * Причина не в вежливости: ошибка распознавания в одной формуле даёт безупречно
 * решённую **чужую** задачу, заметить её может только человек, и стоит этот
 * экран одного взгляда, а ошибка — целого прогона.
 *
 *     Откуда берётся текст
 *     --------------------
 *
 * Из разбора материала (`GET …/materials/{id}/text`), а не из снимка работы:
 * снимок знает условие только после того, как прогон прошёл стадию «приём», а
 * подтверждают его ДО прогона. Материал же разобран сразу после загрузки.
 *
 *     Что делает «поправить»
 *     ----------------------
 *
 * Кладёт исправленный текст **новым материалом** и называет условием его.
 * Правки текста разобранного материала у службы нет и быть не может: материал
 * адресуется хешем содержимого (`materials.Store`), и «поправленный материал»
 * — это по построению другой материал. Прежний остаётся в описи: по нему видно,
 * что именно было распознано, и подменять эту память нельзя.
 */
import { useEffect, useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, SkeletonLines, Textarea } from '@/ui'
import { useMaterialText, useUploadMaterial } from '@/features/projects/data'
import type { Material } from '@/features/projects/types'

import { useSetCondition } from './data'

export function ConditionStep({
  projectId,
  material,
  ocr,
  confirmed,
  onConfirm,
  disabled,
}: {
  projectId: string
  /** Материал-условие проекта. `undefined` — ещё не назван. */
  material: Material | undefined
  /** Читано ли условие распознаванием: тогда проверить его особенно нужно. */
  ocr: boolean
  /** Подтвердил ли человек текст в этот раз. */
  confirmed: boolean
  onConfirm: () => void
  disabled: boolean
}) {
  const t = useT()
  const текст = useMaterialText(projectId, material?.id, !!material)
  const upload = useUploadMaterial()
  const setCondition = useSetCondition()

  const [правим, setПравим] = useState(false)
  const [черновик, setЧерновик] = useState('')
  const [беда, setБеда] = useState<string | null>(null)

  // Черновик заводится из распознанного, а не из пустоты: правят текст, а не
  // пишут его заново.
  useEffect(() => {
    if (правим && !черновик) setЧерновик(текст.data?.text ?? '')
  }, [правим, черновик, текст.data])

  if (!material) {
    return (
      <Карточка>
        <p className="text-sm text-muted">{t('kadai.condition.none')}</p>
      </Карточка>
    )
  }

  async function сохранить() {
    setБеда(null)
    try {
      const принят = await upload.mutateAsync({
        projectId,
        file: new File([черновик], `условие-правка.txt`, { type: 'text/plain' }),
      })
      // Разбор `.txt` — одна строка работы очереди, но она всё же очередь:
      // пробуем назвать условием сразу, а не вышло — говорим словами, а не
      // молча оставляем прежнее условие.
      await новый_условием(принят.pending_id)
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  async function новый_условием(materialId: string, попыток = 12) {
    try {
      await setCondition.mutateAsync({ projectId, materialId })
      setПравим(false)
      setЧерновик('')
      onConfirm()
    } catch (е) {
      if (попыток <= 0) {
        setБеда(errorText(е))
        return
      }
      await new Promise((готово) => setTimeout(готово, 500))
      await новый_условием(materialId, попыток - 1)
    }
  }

  const идёт = upload.isPending || setCondition.isPending

  return (
    <Карточка>
      <header className="flex flex-wrap items-center gap-s2">
        <Icon name="file" size={16} className="text-muted" />
        <span className="font-semibold text-ink-strong">{t('kadai.condition.title')}</span>
        <span className="truncate text-xs text-muted">{material.name}</span>
        {ocr && (
          <span className="rounded-sm bg-warn-bg px-1.5 py-0.5 text-xs text-warn">
            {t('kadai.condition.ocr')}
          </span>
        )}
        {confirmed && !правим && (
          <span className="ml-auto flex items-center gap-1 rounded-sm bg-ok-bg px-1.5 py-0.5 text-xs text-ok">
            <Icon name="check" size={12} />
            {t('kadai.condition.confirmed')}
          </span>
        )}
      </header>

      <p className="text-xs text-muted">{t('kadai.condition.hint')}</p>

      {текст.isPending ? (
        <SkeletonLines count={4} />
      ) : правим ? (
        <Textarea
          value={черновик}
          onChange={(e) => setЧерновик(e.target.value)}
          rows={12}
          aria-label={t('kadai.condition.title')}
          disabled={идёт}
        />
      ) : (
        <pre className="max-h-[280px] overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-surface-2 p-s3 font-mono text-xs text-ink">
          {текст.data?.text || t('kadai.condition.empty')}
        </pre>
      )}

      <div className="flex flex-wrap items-center gap-s2">
        {правим ? (
          <>
            <Button
              variant="primary"
              size="sm"
              loading={идёт}
              disabled={!черновик.trim()}
              onClick={() => void сохранить()}
            >
              {t('kadai.condition.save')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={идёт}
              onClick={() => {
                setПравим(false)
                setЧерновик('')
              }}
            >
              {t('common.action.cancel')}
            </Button>
            <span className="text-xs text-muted">{t('kadai.condition.saveHint')}</span>
          </>
        ) : (
          <>
            <Button
              variant="primary"
              size="sm"
              disabled={disabled || confirmed}
              onClick={onConfirm}
            >
              <Icon name="check" size={14} />
              {t('kadai.condition.ok')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={disabled}
              onClick={() => setПравим(true)}
            >
              <Icon name="edit" size={14} />
              {t('kadai.condition.fix')}
            </Button>
          </>
        )}
      </div>

      {беда && <p className="text-xs text-err">{беда}</p>}
    </Карточка>
  )
}

function Карточка({ children }: { children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
      {children}
    </section>
  )
}
