/**
 * KadaiNewRunPage — страница нового решения в работе: `/kadai/:projectId/new`.
 *
 * Решений в работе несколько: одна задача — одно решение, а задач в работе
 * столько, сколько их задали. У каждого своё условие, свои пожелания, свой ход
 * стадий, свой список блоков и **своя папка файлов контекста** — методичка
 * одной задачи в промпт другой не едет.
 *
 *     Что происходит при «Завести»
 *     ----------------------------
 *
 * Четыре действия подряд, и разорвать их нельзя:
 *
 * 1. **запись решения** — `POST …/kadai/runs`: она заводит и каталог решения на
 *    томе, и строку в журнале работы;
 * 2. **условие материалом** в папку этого решения — файлом как есть или
 *    текстом, завёрнутым в `.txt`: другого способа положить условие у службы
 *    нет, а разбирает материалы очередь, и текст она читает так же, как файл;
 * 3. **файлы контекста** — туда же, по одному запросу на файл;
 * 4. **назвать материал условием** — до этого он обычный материал, и прогон
 *    отказал бы «условие задачи не приложено».
 *
 * Прогон отсюда НЕ запускается. Между приёмом условия и решением стоит шаг
 * «условие распознано», и он живёт на экране решения: жать «Завести» и сразу
 * платить за решение по неверно прочитанному скану — ровно та ошибка, ради
 * которой шаг и заведён.
 */
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Field, Icon, Input, Textarea } from '@/ui'
import { useProject, useUploadMaterial } from '@/features/projects/data'
import { FileDrop } from '@/features/projects/FileDrop'
import { ModelPicker } from '@/features/reports/runControls'
import { useDefaultEndpoint, useProviders } from '@/features/reports/data'

import { ПРИНИМАЕМ } from './ContextFiles'
import { useCreateKadaiRun, useSetCondition, useSetKadaiWishes } from './data'
import { запомнить } from './preset'

export function KadaiNewRunPage() {
  const t = useT()
  const navigate = useNavigate()
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const providers = useProviders()
  // Умолчание пресета: выбор человека из профиля, иначе правило сайта.
  const умолчание = useDefaultEndpoint()

  const создать = useCreateKadaiRun()
  const upload = useUploadMaterial()
  const setCondition = useSetCondition()
  const saveWishes = useSetKadaiWishes()

  const [name, setName] = useState('')
  const [файлом, setФайлом] = useState(true)
  const [файл, setФайл] = useState<File | null>(null)
  const [текст, setТекст] = useState('')
  const [контекст, setКонтекст] = useState<File[]>([])
  const [wishes, setWishes] = useState('')
  const [showTask, setShowTask] = useState(false)
  const [showStructure, setShowStructure] = useState(false)
  const [endpoint, setEndpoint] = useState<string | null>(null)
  const [беда, setБеда] = useState<string | null>(null)

  const пресет = endpoint ?? умолчание
  const идёт = создать.isPending || upload.isPending || setCondition.isPending
  const готово = !!projectId && (файлом ? !!файл : !!текст.trim())

  async function завести() {
    if (!готово) return
    setБеда(null)
    try {
      const решение = await создать.mutateAsync({ projectId, name: name.trim() })
      const условие = файлом
        ? (файл as File)
        : new File([текст], `${имя_файла(name || t('kadai.new.title'))}.txt`, {
            type: 'text/plain',
          })
      // Условие и файлы контекста ложатся в папку этого решения (`run_id` в
      // форме): в промпт уезжают только они, и файл соседней задачи модель не
      // увидит.
      const принят = await upload.mutateAsync({
        projectId,
        file: условие,
        runId: решение.id,
      })
      for (const файл_контекста of контекст) {
        await upload.mutateAsync({ projectId, file: файл_контекста, runId: решение.id })
      }
      // Разбор уехал в очередь: назвать материал условием можно только после
      // него. Здесь мы пробуем сразу — на текстовом условии разбор успевает за
      // один запрос, а если нет, шаг «условие распознано» назовёт его сам.
      try {
        await setCondition.mutateAsync({
          projectId,
          materialId: принят.pending_id,
          runId: решение.id,
        })
      } catch {
        /* материал ещё разбирается — назовёт экран решения */
      }
      // Пожелания ложатся в решение, а не в браузер: прогон начнётся позже —
      // после того, как человек подтвердит распознанное условие, — и до тех пор
      // хранить их в `sessionStorage` значило бы терять их вместе с вкладкой.
      await saveWishes.mutateAsync({
        projectId,
        runId: решение.id,
        wishes: { text: wishes, show_task: showTask, show_structure: showStructure },
      })
      if (пресет) запомнить(решение.id, пресет)
      navigate(`/kadai/${projectId}/${решение.id}`)
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <div className="flex flex-col gap-s4">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <h1 className="truncate font-display text-2xl font-semibold text-ink-strong">
            {t('kadai.new.title')}
          </h1>
          <p className="text-sm text-muted">
            {t('kadai.new.inWork', { work: project.data?.name ?? '' })}
          </p>
        </div>
        <Button variant="ghost" asChild>
          <Link to={`/kadai/${projectId}`}>
            <Icon name="arrowLeft" size={15} />
            {t('kadai.work.toList')}
          </Link>
        </Button>
      </header>

      <section className="flex flex-col gap-s3 rounded-md border border-line bg-surface p-s4 shadow-1">
        <Field label={t('kadai.new.name')} htmlFor="kadai-name" hint={t('kadai.new.nameHint')}>
          <Input
            id="kadai-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('kadai.new.namePlaceholder')}
          />
        </Field>

        <fieldset className="flex flex-col gap-s2">
          <legend className="mb-s1 text-sm font-medium text-ink-strong">
            {t('kadai.new.condition')}
          </legend>
          <div className="flex gap-s3 text-sm text-ink">
            <label className="flex items-center gap-s2">
              <input
                type="radio"
                checked={файлом}
                onChange={() => setФайлом(true)}
                className="accent-[var(--accent)]"
              />
              {t('kadai.new.byFile')}
            </label>
            <label className="flex items-center gap-s2">
              <input
                type="radio"
                checked={!файлом}
                onChange={() => setФайлом(false)}
                className="accent-[var(--accent)]"
              />
              {t('kadai.new.byText')}
            </label>
          </div>
          {файлом ? (
            <div className="flex flex-col gap-1">
              <input
                type="file"
                accept={ПРИНИМАЕМ}
                onChange={(e) => setФайл(e.target.files?.[0] ?? null)}
                aria-label={t('kadai.new.fileLabel')}
                className="text-sm text-ink file:mr-s2 file:rounded-btn file:border file:border-line-strong file:bg-surface-2 file:px-s2 file:py-1 file:text-sm file:text-ink"
              />
              <span className="text-xs text-muted">{t('kadai.new.fileHint')}</span>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              <Textarea
                value={текст}
                onChange={(e) => setТекст(e.target.value)}
                rows={5}
                placeholder={t('kadai.new.textPlaceholder')}
                aria-label={t('kadai.new.textLabel')}
              />
              <span className="text-xs text-muted">{t('kadai.new.textHint')}</span>
            </div>
          )}
        </fieldset>

        <fieldset className="flex flex-col gap-s2">
          <legend className="mb-s1 text-sm font-medium text-ink-strong">
            {t('kadai.new.context')}
          </legend>
          <FileDrop
            multiple
            accept={ПРИНИМАЕМ}
            label={t('kadai.new.contextDrop')}
            hint={t('kadai.new.contextHint')}
            onFiles={(files) => setКонтекст((было) => [...было, ...files])}
          />
          {контекст.length > 0 && (
            <ul className="flex flex-col gap-1 text-xs text-muted">
              {контекст.map((f, i) => (
                <li key={`${f.name}-${i}`} className="flex items-center gap-s2">
                  <Icon name="file" size={14} />
                  <span className="truncate">{f.name}</span>
                  <button
                    type="button"
                    className="ml-auto text-muted hover:text-ink"
                    onClick={() => setКонтекст((было) => было.filter((_, j) => j !== i))}
                  >
                    {t('common.action.delete')}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </fieldset>

        <Field
          label={t('kadai.new.wishes')}
          hint={t('kadai.new.wishesHint')}
          htmlFor="kadai-wishes"
        >
          <Textarea
            id="kadai-wishes"
            value={wishes}
            onChange={(e) => setWishes(e.target.value)}
            rows={3}
            placeholder={t('kadai.new.wishesPlaceholder')}
          />
        </Field>

        <div className="flex flex-col gap-s2 text-sm text-ink">
          <label className="flex items-center gap-s2">
            <input
              type="checkbox"
              checked={showTask}
              onChange={(e) => setShowTask(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            {t('kadai.new.showTask')}
          </label>
          <label className="flex items-center gap-s2">
            <input
              type="checkbox"
              checked={showStructure}
              onChange={(e) => setShowStructure(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            {t('kadai.new.showStructure')}
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-s3 border-t border-line pt-s3">
          <ModelPicker
            providers={providers.data}
            value={пресет}
            onChange={setEndpoint}
            disabled={идёт}
          />
          <Button
            variant="primary"
            className="ml-auto"
            disabled={!готово}
            loading={идёт}
            onClick={() => void завести()}
          >
            {t('kadai.new.submit')}
          </Button>
        </div>

        {беда && <p className="text-sm text-err">{беда}</p>}
      </section>
    </div>
  )
}

/** Имя файла условия из имени решения: без знаков, которые ломают путь. */
function имя_файла(name: string): string {
  const чистое = name
    .trim()
    .replace(/[^\p{L}\p{N}\-_ ]/gu, '')
    .replace(/\s+/g, '-')
  return чистое ? чистое.slice(0, 40) : 'условие'
}
