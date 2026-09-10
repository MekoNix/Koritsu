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
 * — это по построению другой материал. Прежний остаётся в папке решения: по
 * нему видно, что именно было распознано, и подменять эту память нельзя. Модели
 * он с этой минуты не показывается (`Project.past_conditions`) — иначе она
 * получила бы два условия сразу и решала бы по тому, которое человек исправлял.
 *
 *     Пока условие не названо
 *     -----------------------
 *
 * Шаг говорит «условие не названо» и предлагает выбрать файл из папки решения.
 * Считать условием первый файл папки нельзя: «первый» там оказывается то скан,
 * то методичка, то прежняя версия условия, и человек платит за решение чужой
 * задачи, ничего не выбирая. Название — действие с одним нажатием и видимым
 * ответом, а не догадка экрана.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, SkeletonLines, Textarea } from '@/ui'
import { useMaterialText, useUploadMaterial } from '@/features/projects/data'
import type { Material } from '@/features/projects/types'

import { useContextMaterials, useSetCondition } from './data'

export function ConditionStep({
  projectId,
  runId,
  material,
  named,
  ocr,
  confirmed,
  onConfirm,
  disabled,
}: {
  projectId: string
  /**
   * Решение, чьё условие правится. У каждого оно своё, и поправленный текст
   * ложится в его же папку контекста: иначе правка одной задачи приехала бы в
   * промпт соседней.
   */
  runId: string
  /** Материал-условие решения. `undefined` — назван, но ещё не найден в описи. */
  material: Material | undefined
  /**
   * Назвало ли решение условие вообще. Отдельно от `material`, потому что между
   * «назвали» и «материал появился в описи» проходит секунда: правку кладут
   * новым файлом, и опись перечитывается после. Без этого шаг в ту самую
   * секунду говорил бы «условие не названо» человеку, который его только что
   * назвал.
   */
  named: boolean
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
  // Папка решения — из чего выбирают условие, пока его не назвали. Тот же ключ
  // кэша, что у списка файлов ниже: второго запроса за тем же ответом нет.
  const папка = useContextMaterials(projectId, runId)

  const [правим, setПравим] = useState(false)
  const [черновик, setЧерновик] = useState('')
  const [беда, setБеда] = useState<string | null>(null)

  // Черновик заводится из распознанного один раз — в момент входа в правку, а
  // не наблюдением за пустотой поля. Наблюдение выглядело безобиднее и делало
  // поле неочищаемым: стёртый текст тут же считался «черновика ещё нет» и
  // подставлялся заново, так что Ctrl+A и Delete не давали ничего.
  function править() {
    setЧерновик(текст.data?.text ?? '')
    setПравим(true)
  }

  /** Назвать условием файл, выбранный человеком в папке решения. */
  function выбрать(materialId: string) {
    setБеда(null)
    // `useFileName` — истина: файл принёс человек, и его имя говорит, какая это
    // задача. Безымянному решению служба возьмёт имя отсюда.
    setCondition.mutate(
      { projectId, materialId, runId, useFileName: true },
      { onError: (е) => setБеда(errorText(е)) },
    )
  }

  if (!material) {
    // Условие названо, а материала под рукой ещё нет: ждём опись, а не
    // предлагаем выбрать файл заново.
    if (named) {
      return (
        <Карточка>
          <SkeletonLines count={4} />
        </Карточка>
      )
    }
    const свои = папка.data ?? []
    return (
      <Карточка>
        <header className="flex flex-wrap items-center gap-s2">
          <Icon name="file" size={16} className="text-muted" />
          <span className="font-semibold text-ink-strong">{t('kadai.condition.unnamed')}</span>
        </header>
        <p className="text-sm text-muted">{t('kadai.condition.none')}</p>
        {папка.isPending ? (
          <SkeletonLines count={2} />
        ) : свои.length === 0 ? (
          <p className="text-xs text-muted">{t('kadai.condition.noneEmpty')}</p>
        ) : (
          <>
            <p className="text-xs text-muted">{t('kadai.condition.pickHint')}</p>
            <ul className="flex flex-col gap-1 text-sm text-ink" data-testid="kadai-condition-pick">
              {свои.map((m) => (
                <li key={m.id} className="flex items-center gap-s2">
                  <Icon name="file" size={14} className="text-muted" />
                  <span className="truncate">{m.name}</span>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="ml-auto"
                    disabled={disabled || setCondition.isPending}
                    onClick={() => выбрать(m.id)}
                  >
                    {t('kadai.condition.pick')}
                  </Button>
                </li>
              ))}
            </ul>
          </>
        )}
        {беда && <p className="text-xs text-err">{беда}</p>}
      </Карточка>
    )
  }

  async function сохранить() {
    setБеда(null)
    try {
      const принят = await upload.mutateAsync({
        projectId,
        runId,
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
      // `useFileName: false` — имя решению отсюда не берётся: файл с правкой
      // назвали мы сами, и «условие-правка» именем задачи не является.
      await setCondition.mutateAsync({ projectId, materialId, runId, useFileName: false })
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
            <span className="text-xs text-muted">
              {черновик.trim() ? t('kadai.condition.saveHint') : t('kadai.condition.emptyDraft')}
            </span>
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
              disabled={disabled || текст.isPending}
              onClick={править}
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
