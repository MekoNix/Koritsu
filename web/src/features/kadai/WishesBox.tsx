/**
 * WishesBox — пожелания к работе на экране самой работы.
 *
 * Раньше пожелания писались один раз, в форме заведения, и жили в
 * `sessionStorage`: службе негде было их держать до первого прогона. Отсюда две
 * беды сразу — они терялись вместе с вкладкой и их нельзя было передумать.
 * Теперь они лежат в проекте (`PUT …/kadai/wishes`), и это же делает их
 * правимыми: коробка стоит на экране работы, рядом с кнопкой прогона.
 *
 * **Пожелания читает прогон, а не мы.** Служба берёт их из проекта, когда в
 * задании их нет (`runs/handlers/kadai_run.py`), поэтому сохранённое здесь
 * доедет до модели само. Второго места, откуда они уезжают, не заводится.
 *
 * **Правка доходит до модели только на первом прогоне.** Сценарий читает
 * пожелания, когда заводит работу, и заведённой их уже не меняет — там они
 * записаны в задание. Молчать об этом нельзя: человек, правящий их на середине
 * работы, вправе знать, что сегодня это ни на что не повлияет.
 */
import { useEffect, useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Field, Textarea } from '@/ui'

import type { Wishes } from './stages'

export function WishesBox({
  wishes,
  loading,
  saving,
  error,
  started,
  disabled,
  onSave,
}: {
  wishes: Wishes | undefined
  loading: boolean
  saving: boolean
  error: unknown
  /** Заведена ли работа: у заведённой правка на прогон уже не влияет. */
  started: boolean
  disabled: boolean
  onSave: (wishes: Wishes) => void
}) {
  const t = useT()
  const [text, setText] = useState('')
  const [showTask, setShowTask] = useState(false)
  const [showStructure, setShowStructure] = useState(false)
  const [правили, setПравили] = useState(false)

  // Приехавшее с сервера кладётся в поля один раз — пока человек их не трогал.
  // Затирать набранное ответом запроса, пришедшим позже, значило бы стереть
  // текст под руками у того, кто его пишет.
  useEffect(() => {
    if (правили || !wishes) return
    setText(wishes.text)
    setShowTask(wishes.show_task)
    setShowStructure(wishes.show_structure)
  }, [wishes, правили])

  const изменено =
    !!wishes &&
    (text !== wishes.text ||
      showTask !== wishes.show_task ||
      showStructure !== wishes.show_structure)

  function поменять(изменить: () => void) {
    setПравили(true)
    изменить()
  }

  return (
    <section className="flex flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
      <Field label={t('kadai.wishes.title')} hint={t('kadai.wishes.hint')} htmlFor="kadai-wishes">
        <Textarea
          id="kadai-wishes"
          value={text}
          onChange={(e) => поменять(() => setText(e.target.value))}
          rows={3}
          disabled={disabled || loading}
          placeholder={t('kadai.new.wishesPlaceholder')}
        />
      </Field>

      <div className="flex flex-col gap-1 text-sm text-ink">
        <label className="flex items-center gap-s2">
          <input
            type="checkbox"
            checked={showTask}
            disabled={disabled || loading}
            onChange={(e) => поменять(() => setShowTask(e.target.checked))}
            className="accent-[var(--accent)]"
          />
          {t('kadai.new.showTask')}
        </label>
        <label className="flex items-center gap-s2">
          <input
            type="checkbox"
            checked={showStructure}
            disabled={disabled || loading}
            onChange={(e) => поменять(() => setShowStructure(e.target.checked))}
            className="accent-[var(--accent)]"
          />
          {t('kadai.new.showStructure')}
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-s2">
        {started && <span className="text-xs text-muted">{t('kadai.wishes.tooLate')}</span>}
        <Button
          variant="secondary"
          size="sm"
          className="ml-auto"
          disabled={disabled || !изменено}
          loading={saving}
          onClick={() => {
            setПравили(false)
            onSave({ text, show_task: showTask, show_structure: showStructure })
          }}
        >
          {t('kadai.wishes.save')}
        </Button>
      </div>

      {!!error && <p className="text-xs text-err">{errorText(error)}</p>}
    </section>
  )
}
