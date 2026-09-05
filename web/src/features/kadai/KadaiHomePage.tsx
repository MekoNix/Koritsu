/**
 * KadaiHomePage — главная модуля «Задания»: список работ и заведение новой.
 *
 * Своя страница в сайдбаре, а не вкладка отчётов: здесь
 * другой вход — не шаблон с тегами, а одна задача условием, — и другой путь
 * дальше.
 *
 *     Что происходит при «Завести»
 *     ----------------------------
 *
 * Три действия подряд, и разорвать их нельзя:
 *
 * 1. **проект без шаблона** — у работы `kadai` шаблона нет вовсе, документ
 *    собирается из списка блоков;
 * 2. **условие материалом** — файлом как есть или текстом, завёрнутым в
 *    `.txt`: другого способа положить условие в проект у службы нет, а
 *    разбирает материалы очередь (`parse`), и текст она читает так же, как
 *    файл;
 * 3. **назвать материал условием** — до этого он обычный материал, и прогон
 *    отказал бы «условие задачи не приложено».
 *
 * Прогон отсюда НЕ запускается. Между приёмом условия и решением стоит шаг
 * «условие распознано», и он живёт на экране работы: жать
 * «Завести» и сразу платить за решение по неверно прочитанному скану — ровно
 * та ошибка, ради которой шаг и заведён.
 *
 * **Цена и остаток показаны до нажатия** — из `GET /api/usage`, тем же
 * компонентом, что в отчётах: цена вида задания и остаток месяца приезжают
 * одним ответом и разойтись не могут.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace, useUsage } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, EmptyState, ErrorState, Field, Icon, Input, SkeletonLines, Textarea } from '@/ui'
import { useCreateProject, useProjects, useUploadMaterial } from '@/features/projects/data'
import { ModelPicker, PriceHint } from '@/features/reports/runControls'
import { useProviders, useDefaultEndpoint } from '@/features/reports/data'

import { useSetCondition, useSetKadaiWishes } from './data'
import { KADAI_RUN } from './types'

/** Что принимает разбор материалов: те же виды, что и опись проекта. */
const ПРИНИМАЕМ = '.docx,.doc,.pdf,.txt,.md,.png,.jpg,.jpeg,.py,.cs,.cpp,.c,.h'

export function KadaiHomePage() {
  const t = useT()
  const navigate = useNavigate()
  const workspace = useCurrentWorkspace()
  const projects = useProjects(workspace.data?.id)
  const usage = useUsage()
  const providers = useProviders()
  // Умолчание пресета: выбор человека из профиля, иначе правило сайта.
  const умолчание = useDefaultEndpoint()

  const [query, setQuery] = useState('')
  const [открыта, setОткрыта] = useState(false)

  const найденные = useMemo(() => {
    const запрос = query.trim().toLowerCase()
    const все = projects.data ?? []
    return запрос ? все.filter((p) => p.name.toLowerCase().includes(запрос)) : все
  }, [projects.data, query])

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink-strong">
            {t('kadai.home.title')}
          </h1>
          <p className="max-w-[64ch] text-sm text-muted">{t('kadai.home.subtitle')}</p>
        </div>
        <Button variant="primary" onClick={() => setОткрыта((v) => !v)}>
          <Icon name={открыта ? 'close' : 'plus'} size={16} />
          {открыта ? t('common.action.cancel') : t('kadai.home.create')}
        </Button>
      </header>

      {открыта && (
        <NewWork
          workspaceId={workspace.data?.id}
          onDone={(projectId) => navigate(`/kadai/${projectId}`)}
          providers={providers.data}
          priceHint={<PriceHint kind={KADAI_RUN} usage={usage.data} />}
          defaultEndpoint={умолчание}
        />
      )}

      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t('kadai.home.search')}
        aria-label={t('kadai.home.search')}
        className="max-w-[420px]"
      />

      {projects.isPending ? (
        <SkeletonLines count={6} />
      ) : projects.isError ? (
        <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
      ) : найденные.length === 0 ? (
        <EmptyState
          icon="tasks"
          title={projects.data?.length ? t('kadai.home.nothingFound') : t('kadai.home.emptyTitle')}
          text={projects.data?.length ? undefined : t('kadai.home.emptyText')}
          action={
            projects.data?.length ? undefined : (
              <Button variant="primary" onClick={() => setОткрыта(true)}>
                {t('kadai.home.create')}
              </Button>
            )
          }
        />
      ) : (
        <ul className="grid gap-s3 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]">
          {найденные.map((p) => (
            <li key={p.id}>
              <Link
                to={`/kadai/${p.id}`}
                className="flex h-full flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1 transition-colors hover:border-line-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <span className="flex items-center gap-s2">
                  <Icon name="tasks" size={16} style={{ color: 'var(--mod-kadai)' }} />
                  <span className="truncate font-semibold text-ink-strong">{p.name}</span>
                </span>
                <span className="text-xs text-muted">
                  {t('kadai.home.updated', { at: когда(p.updated_at) })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Форма заведения работы: имя, условие файлом или текстом, пожелания, пресет.
 *
 * Условие текстом заворачивается в `.txt` и уезжает тем же маршрутом, что
 * файл: у службы один путь приёма — через очередь, — и второй
 * — «а текст положите значением» — означал бы, что условие бывает двух видов и
 * прочитаны они будут по-разному.
 */
function NewWork({
  workspaceId,
  onDone,
  providers,
  priceHint,
  defaultEndpoint,
}: {
  workspaceId: string | undefined
  onDone: (projectId: string) => void
  providers: ReturnType<typeof useProviders>['data']
  priceHint: React.ReactNode
  defaultEndpoint: string | null
}) {
  const t = useT()
  const create = useCreateProject()
  const upload = useUploadMaterial()
  const setCondition = useSetCondition()
  const saveWishes = useSetKadaiWishes()

  const [name, setName] = useState('')
  const [файлом, setФайлом] = useState(true)
  const [файл, setФайл] = useState<File | null>(null)
  const [текст, setТекст] = useState('')
  const [wishes, setWishes] = useState('')
  const [showTask, setShowTask] = useState(false)
  const [showStructure, setShowStructure] = useState(false)
  const [endpoint, setEndpoint] = useState<string | null>(null)
  const [беда, setБеда] = useState<string | null>(null)

  const пресет = endpoint ?? defaultEndpoint
  const идёт = create.isPending || upload.isPending || setCondition.isPending
  const готово = !!workspaceId && !!name.trim() && (файлом ? !!файл : !!текст.trim())

  async function завести() {
    if (!workspaceId || !готово) return
    setБеда(null)
    try {
      const проект = await create.mutateAsync({ workspaceId, name: name.trim(), template: null })
      const условие = файлом
        ? (файл as File)
        : new File([текст], `${имя_файла(name)}.txt`, { type: 'text/plain' })
      const принят = await upload.mutateAsync({ projectId: проект.id, file: условие })
      // Разбор уехал в очередь: назвать материал условием можно только после
      // него, и делает это экран работы, увидев материал в описи. Здесь мы
      // пробуем сразу — на текстовом условии разбор успевает за один запрос, а
      // если нет, шаг «условие распознано» назовёт его сам.
      try {
        await setCondition.mutateAsync({ projectId: проект.id, materialId: принят.pending_id })
      } catch {
        /* материал ещё разбирается — назовёт экран работы */
      }
      // Пожелания ложатся в проект, а не в браузер: прогон начнётся позже —
      // после того, как человек подтвердит распознанное условие, — и до тех пор
      // хранить их в `sessionStorage` значило бы терять их вместе с вкладкой.
      // Читает их потом сам прогон, если в задании пожеланий нет.
      await saveWishes.mutateAsync({
        projectId: проект.id,
        wishes: { text: wishes, show_task: showTask, show_structure: showStructure },
      })
      if (пресет) sessionStorage.setItem(`kadai.endpoint.${проект.id}`, пресет)
      onDone(проект.id)
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <section className="flex flex-col gap-s3 rounded-md border border-line bg-surface p-s4 shadow-1">
      <h2 className="font-display text-lg font-semibold text-ink-strong">{t('kadai.new.title')}</h2>

      <Field label={t('kadai.new.name')} htmlFor="kadai-name">
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

      <Field label={t('kadai.new.wishes')} hint={t('kadai.new.wishesHint')} htmlFor="kadai-wishes">
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
        <ModelPicker providers={providers} value={пресет} onChange={setEndpoint} disabled={идёт} />
        <span className="text-xs text-muted">{priceHint}</span>
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
  )
}

/** Имя файла условия из имени работы: без знаков, которые ломают путь. */
function имя_файла(name: string): string {
  const чистое = name
    .trim()
    .replace(/[^\p{L}\p{N}\-_ ]/gu, '')
    .replace(/\s+/g, '-')
  return чистое ? чистое.slice(0, 40) : 'условие'
}

/** Время человеку: дата и часы, без секунд. */
function когда(iso: string): string {
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
