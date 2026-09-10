/**
 * ConditionStep — первый шаг работы: «вот условие, всё верно?».
 *
 * Отдельный шаг с двумя кнопками стоит здесь намеренно.
 * Причина не в вежливости: ошибка распознавания в одной формуле даёт безупречно
 * решённую **чужую** задачу, заметить её может только человек, и стоит этот
 * экран одного взгляда, а ошибка — целого прогона.
 *
 *     Условие — текст, а не файл
 *     --------------------------
 *
 * Решают по тексту: файл (скан, `docx`, `pdf`) — лишь один из способов его
 * принести, и распознанное из него ложится в состояние решения строкой
 * (`condition_text` снимка). Поэтому и правят здесь текст на месте — поле,
 * кнопка, `PUT …/kadai/condition` с новой строкой.
 *
 * Правка не заводит второго файла. Материал адресуется содержимым
 * (`materials.Store`), и «поправленный материал» — это по построению другой
 * материал: папка решения набиралась бы версиями условия, из которых модели
 * показывается одна, а человек видит все. Файл, из которого условие вынуто,
 * остаётся приложенным как был: сверить прочитанное со сканом можно только по
 * самому скану.
 *
 *     Пока условия нет
 *     ----------------
 *
 * Шаг говорит «условие не названо» и предлагает выбрать файл из папки решения.
 * Считать условием первый файл папки нельзя: «первым» там оказывается то скан,
 * то методичка, и человек платит за решение чужой задачи, ничего не выбирая.
 * Название — действие с одним нажатием и видимым ответом, а не догадка экрана.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, SkeletonLines, Textarea } from '@/ui'
import { useMaterialText } from '@/features/projects/data'
import type { Material } from '@/features/projects/types'

import { useContextMaterials, useSetCondition, useSetConditionText } from './data'

export function ConditionStep({
  projectId,
  runId,
  material,
  text,
  named,
  ocr,
  confirmed,
  onConfirm,
  disabled,
}: {
  projectId: string
  /**
   * Решение, чьё условие правится. У каждого оно своё, и поправленный текст
   * ложится в его же состояние: иначе правка одной задачи приехала бы в промпт
   * соседней.
   */
  runId: string
  /** Файл, из которого условие вынуто. `undefined` — условие набрано текстом. */
  material: Material | undefined
  /** Условие текстом из состояния решения. Пусто — его туда ещё не положили. */
  text: string
  /**
   * Назван ли файл условия. Отдельно от `material`, потому что между «назвали»
   * и «материал появился в описи» проходит секунда, и без этого шаг в ту самую
   * секунду говорил бы «условие не названо» человеку, который его только что
   * назвал.
   */
  named: boolean
  /** Читан ли файл распознаванием: тогда проверить текст особенно нужно. */
  ocr: boolean
  /** Подтвердил ли человек текст в этот раз. */
  confirmed: boolean
  onConfirm: () => void
  disabled: boolean
}) {
  const t = useT()
  // Разбор файла спрашивается, только пока текста условия в состоянии нет:
  // после первого же подтверждения или правки решают по строке, и второй ответ
  // с тем же текстом был бы лишним запросом на каждое открытие экрана.
  const из_файла = useMaterialText(projectId, material?.id, !!material && !text)
  const setCondition = useSetCondition()
  const setText = useSetConditionText()
  // Папка решения — из чего выбирают условие, пока его не назвали. Тот же ключ
  // кэша, что у списка файлов ниже: второго запроса за тем же ответом нет.
  const папка = useContextMaterials(projectId, runId)

  const [правим, setПравим] = useState(false)
  const [черновик, setЧерновик] = useState('')
  const [беда, setБеда] = useState<string | null>(null)

  const показанный = text || из_файла.data?.text || ''

  // Черновик заводится из показанного один раз — в момент входа в правку, а не
  // наблюдением за пустотой поля. Наблюдение выглядело безобиднее и делало поле
  // неочищаемым: стёртый текст тут же считался «черновика ещё нет» и
  // подставлялся заново, так что Ctrl+A и Delete не давали ничего.
  function править() {
    setЧерновик(показанный)
    setПравим(true)
  }

  /** Назвать файлом условия то, что человек выбрал в папке решения. */
  function выбрать(materialId: string) {
    setБеда(null)
    // `useFileName` — истина: файл принёс человек, и его имя говорит, какая это
    // задача. Безымянному решению служба возьмёт имя отсюда.
    setCondition.mutate(
      { projectId, materialId, runId, useFileName: true },
      { onError: (е) => setБеда(errorText(е)) },
    )
  }

  function сохранить() {
    setБеда(null)
    setText.mutate(
      { projectId, runId, text: черновик.trim() },
      {
        onSuccess: () => {
          setПравим(false)
          setЧерновик('')
          // Поправленное условие подтверждать второй раз незачем: человек
          // только что написал его своей рукой.
          onConfirm()
        },
        onError: (е) => setБеда(errorText(е)),
      },
    )
  }

  // Ни текста, ни файла: решать нечего, и шаг занят выбором условия.
  if (!text && !material) {
    // Файл условия назван, а материала под рукой ещё нет: ждём опись, а не
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

  const идёт = setText.isPending || setCondition.isPending

  return (
    <Карточка>
      <header className="flex flex-wrap items-center gap-s2">
        <Icon name="file" size={16} className="text-muted" />
        <span className="font-semibold text-ink-strong">
          {t(material ? 'kadai.condition.title' : 'kadai.condition.titleText')}
        </span>
        {material && <span className="truncate text-xs text-muted">{material.name}</span>}
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

      {из_файла.isPending ? (
        <SkeletonLines count={4} />
      ) : правим ? (
        <Textarea
          value={черновик}
          onChange={(e) => setЧерновик(e.target.value)}
          rows={12}
          aria-label={t('kadai.condition.titleText')}
          disabled={идёт}
        />
      ) : (
        <pre className="max-h-[280px] overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-surface-2 p-s3 font-mono text-xs text-ink">
          {показанный || t('kadai.condition.empty')}
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
              onClick={сохранить}
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
              disabled={disabled || из_файла.isPending}
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
