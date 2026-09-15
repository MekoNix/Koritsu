/**
 * GeneratePage — создание набора агентом: `/cards/generate`.
 *
 * С параметрами `?project=&set=` страница дополняет существующий набор: вход
 * тот же, а черновик по «Сохранить» добавляется в набор новой версией.
 *
 * **Что уходит агенту.** Тема и описание, список вопросов (строка — вопрос,
 * строка-заголовок — раздел, из разделов получаются темы), отмеченные файлы,
 * сколько карточек (всего или на тему, до 200 за раз), длина ответа и язык.
 * Запуск платный, поэтому он только по нажатию «Создать», и до нажатия видны
 * пресет модели и цена запуска, если служба её называет.
 *
 * **Две раскладки.** На компьютере форма в две колонки: источник слева,
 * параметры и запуск справа. На телефоне — пошаговая форма «Тема → Вопросы и
 * файлы → Количество → Запуск» с «Назад/Далее» внизу под пальцем: длинная
 * форма одним экраном на телефоне прячет кнопку запуска за тремя прокрутками.
 *
 * После «Создать» человек сразу уходит на черновик: генерация идёт заданием, и
 * черновик показывает её ход и карточки по мере готовности.
 */
import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace, useUsage } from '@/api/hooks'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { BetaTag, Button, Field, ForbiddenState, Icon, Input, Segmented, Select, Textarea } from '@/ui'
import { canEditWorkspace } from '@/features/projects/data'
import { useDefaultEndpoint, useProviders } from '@/features/reports/data'
import { ModelPicker } from '@/features/reports/runControls'

import { useIsPhone } from '../hooks/useIsPhone'
import { materialReady, useCardsMaterials, useGenerate, type AnswerLength } from './data'
import { MaterialsPicker } from './MaterialsPicker'

/** Потолок карточек за один запуск (договор службы). */
export const MAX_CARDS = 200

/** Языки набора на выбор; код уходит в `language` и во фронтматтер. */
export const LANGUAGES = ['ru', 'en', 'de', 'fr', 'es', 'zh', 'ja'] as const

const STEPS = ['topic', 'sources', 'count', 'run'] as const
type Step = (typeof STEPS)[number]

/** Состояние формы целиком: одно на обе раскладки. */
type Form = {
  topic: string
  description: string
  questions: string
  materialIds: string[]
  count: number
  perTopic: boolean
  length: AnswerLength
  language: string
}

const EMPTY: Form = {
  topic: '',
  description: '',
  questions: '',
  materialIds: [],
  count: 30,
  perTopic: false,
  length: 'short',
  language: 'ru',
}

/** Путь черновика; режим дополнения едет в адресе, чтобы пережить перезагрузку. */
function draftPath(draftId: string, projectId?: string | null, setId?: string | null): string {
  const base = `/cards/drafts/${encodeURIComponent(draftId)}`
  return projectId && setId
    ? `${base}?project=${encodeURIComponent(projectId)}&set=${encodeURIComponent(setId)}`
    : base
}

export default function GeneratePage() {
  const t = useT()
  const phone = useIsPhone()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const projectId = params.get('project')
  const setId = params.get('set')
  const append = !!projectId && !!setId

  const workspace = useCurrentWorkspace()
  const workspaceId = workspace.data?.id
  const providers = useProviders()
  const defaultEndpoint = useDefaultEndpoint()
  const usage = useUsage()
  const materials = useCardsMaterials(workspaceId)
  const generate = useGenerate()

  const [form, setForm] = useState<Form>(EMPTY)
  const [endpoint, setEndpoint] = useState<string | null>(null)
  const [step, setStep] = useState<Step>('topic')

  const preset = endpoint ?? defaultEndpoint
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }))

  // Файлы, которые ещё разбираются: агент читает разобранный текст, и запуск
  // до конца разбора ушёл бы без них.
  const parsing = form.materialIds.some((id) => {
    const m = materials.data?.find((x) => x.material_id === id)
    return !!m && !materialReady(m)
  })
  const hasSource = !!form.topic.trim() || !!form.questions.trim() || form.materialIds.length > 0
  const countOk = Number.isInteger(form.count) && form.count >= 1 && form.count <= MAX_CARDS
  const ready = !!workspaceId && hasSource && countOk && !!preset && !parsing

  const price = usage.data?.prices?.cards_generate

  function submit() {
    if (!ready || !workspaceId || !preset) return
    const prompt = [form.topic.trim(), form.description.trim()].filter(Boolean).join('\n\n')
    generate.mutate(
      {
        workspace_id: workspaceId,
        ...(append ? { project_id: projectId as string, set_id: setId as string } : {}),
        prompt,
        questions: form.questions.trim() || undefined,
        material_ids: form.materialIds.length ? form.materialIds : undefined,
        count: form.count,
        // Служба считает `count` всего, а `per_topic` — число карточек на тему.
        per_topic: form.perTopic ? form.count : null,
        length: form.length,
        language: form.language,
        endpoint: preset,
      },
      { onSuccess: (r) => navigate(draftPath(r.draft_id, projectId, setId)) },
    )
  }

  if (workspace.data && !canEditWorkspace(workspace.data.role)) {
    return <ForbiddenState action={<BackLink append={append} projectId={projectId} setId={setId} />} />
  }

  const sections = {
    topic: (
      <Section title={t('cards.generate.topic.title')}>
        <Field label={t('cards.generate.topic.label')} htmlFor="cards-gen-topic">
          <Input
            id="cards-gen-topic"
            value={form.topic}
            onChange={(e) => set('topic', e.target.value)}
            placeholder={t('cards.generate.topic.placeholder')}
          />
        </Field>
        <Field
          label={t('cards.generate.description.label')}
          hint={t('cards.generate.description.hint')}
          htmlFor="cards-gen-description"
        >
          <Textarea
            id="cards-gen-description"
            rows={phone ? 5 : 3}
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            placeholder={t('cards.generate.description.placeholder')}
          />
        </Field>
      </Section>
    ),
    sources: (
      <>
        <Section title={t('cards.generate.questions.title')}>
          <Field hint={t('cards.generate.questions.hint')} htmlFor="cards-gen-questions">
            <Textarea
              id="cards-gen-questions"
              rows={phone ? 10 : 12}
              value={form.questions}
              onChange={(e) => set('questions', e.target.value)}
              placeholder={t('cards.generate.questions.placeholder')}
              className="font-mono text-sm"
            />
          </Field>
          {form.questions.trim() && (
            <p className="text-xs text-muted">
              {t('cards.generate.questions.count', { n: countQuestions(form.questions) })}
            </p>
          )}
        </Section>
        <Section title={t('cards.generate.files.title')}>
          <MaterialsPicker
            workspaceId={workspaceId}
            selected={form.materialIds}
            onChange={(ids) => set('materialIds', ids)}
            disabled={generate.isPending}
          />
        </Section>
      </>
    ),
    count: (
      <Section title={t('cards.generate.count.title')}>
        <Segmented
          label={t('cards.generate.count.mode')}
          value={form.perTopic ? 'topic' : 'total'}
          onChange={(v) => set('perTopic', v === 'topic')}
          options={[
            { value: 'total', label: t('cards.generate.count.total') },
            { value: 'topic', label: t('cards.generate.count.perTopic') },
          ]}
        />
        <div className="flex flex-wrap items-end gap-s2">
          {[10, 20, 30, 50].map((n) => (
            <Button
              key={n}
              size={phone ? 'lg' : 'sm'}
              variant={form.count === n ? 'primary' : 'secondary'}
              onClick={() => set('count', n)}
            >
              {n}
            </Button>
          ))}
          <Input
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_CARDS}
            value={Number.isFinite(form.count) ? form.count : ''}
            onChange={(e) => set('count', Math.trunc(Number(e.target.value)))}
            aria-label={t('cards.generate.count.custom')}
            wrapperClassName="w-24"
          />
        </div>
        <p className={cn('text-xs', countOk ? 'text-muted' : 'text-err')}>
          {countOk
            ? t(form.perTopic ? 'cards.generate.count.hintTopic' : 'cards.generate.count.hintTotal')
            : t('cards.generate.count.limit', { max: MAX_CARDS })}
        </p>

        <Field label={t('cards.generate.length.label')}>
          <Segmented
            label={t('cards.generate.length.label')}
            value={form.length}
            onChange={(v) => set('length', v)}
            options={[
              { value: 'short', label: t('cards.generate.length.short') },
              { value: 'full', label: t('cards.generate.length.full') },
            ]}
          />
        </Field>
        <p className="text-xs text-muted">
          {t(form.length === 'short' ? 'cards.generate.length.shortHint' : 'cards.generate.length.fullHint')}
        </p>

        <Select
          label={t('cards.generate.language.label')}
          value={form.language}
          onChange={(e) => set('language', e.target.value)}
        >
          {LANGUAGES.map((code) => (
            <option key={code} value={code}>
              {t(`cards.generate.language.${code}`)}
            </option>
          ))}
        </Select>
      </Section>
    ),
    run: (
      <Section title={t('cards.generate.run.title')}>
        {append && <p className="text-sm text-muted">{t('cards.generate.run.appendHint')}</p>}
        <ModelPicker
          providers={providers.data}
          value={preset}
          onChange={setEndpoint}
          disabled={generate.isPending}
        />
        {!preset && providers.isSuccess && (
          <p className="text-sm text-warn">
            {t('cards.generate.run.noEndpoint')}{' '}
            <Link to="/settings/agent" className="underline">
              {t('cards.generate.run.toSettings')}
            </Link>
          </p>
        )}
        {typeof price === 'number' && (
          <p className="text-sm text-muted" data-testid="cards-generate-price">
            {t('cards.generate.run.price', { n: price })}
            {typeof usage.data?.remaining_units === 'number' &&
              ` · ${t('cards.generate.run.remaining', { n: usage.data.remaining_units })}`}
          </p>
        )}
        <Summary form={form} />
        {!hasSource && <p className="text-xs text-warn">{t('cards.generate.run.needSource')}</p>}
        {parsing && <p className="text-xs text-muted">{t('cards.generate.run.waitFiles')}</p>}
        {generate.isError && <p className="text-sm text-err">{errorText(generate.error)}</p>}
        {!phone && (
          <Button variant="agent" size="lg" disabled={!ready} loading={generate.isPending} onClick={submit}>
            <Icon name="agent" size={16} />
            {t('cards.generate.run.submit')}
          </Button>
        )}
      </Section>
    ),
  } satisfies Record<Step, ReactNode>

  const header = (
    <header className="flex flex-wrap items-end justify-between gap-s3">
      <div className="min-w-0">
        <h1 className="flex items-center gap-s2 font-display text-2xl font-semibold text-ink-strong">
          {t(append ? 'cards.generate.titleAppend' : 'cards.generate.title')}
          <BetaTag label={t('shell.beta')} />
        </h1>
        <p className="max-w-[64ch] text-sm text-muted">{t('cards.generate.subtitle')}</p>
      </div>
      {!phone && <BackLink append={append} projectId={projectId} setId={setId} />}
    </header>
  )

  if (!phone) {
    return (
      <div className="flex flex-col gap-s4">
        {header}
        <div className="grid items-start gap-s4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-s4">
            {sections.topic}
            {sections.sources}
          </div>
          <div className="flex min-w-0 flex-col gap-s4 lg:sticky lg:top-s4">
            {sections.count}
            {sections.run}
          </div>
        </div>
      </div>
    )
  }

  // ── телефон: шаги ──
  const at = STEPS.indexOf(step)
  const last = at === STEPS.length - 1
  return (
    <div className="flex flex-col gap-s3 pb-[calc(88px+env(safe-area-inset-bottom))]">
      {header}
      <ol className="flex gap-1" aria-label={t('cards.generate.steps.label')}>
        {STEPS.map((s, i) => (
          <li key={s} className="flex-1">
            <button
              type="button"
              onClick={() => setStep(s)}
              aria-current={s === step ? 'step' : undefined}
              className={cn(
                'flex min-h-11 w-full flex-col items-center justify-center gap-1 text-[11px]',
                i <= at ? 'text-ink-strong' : 'text-muted',
              )}
            >
              <span className={cn('h-1 w-full rounded-full', i <= at ? 'bg-accent' : 'bg-line')} />
              {t(`cards.generate.steps.${s}`)}
            </button>
          </li>
        ))}
      </ol>

      {sections[step]}

      <div className="fixed inset-x-0 bottom-0 z-40 flex gap-s2 border-t border-line bg-surface px-s3 pt-s2 pb-[calc(env(safe-area-inset-bottom)+8px)] shadow-2">
        <Button
          size="lg"
          variant="secondary"
          className="flex-1"
          onClick={() => (at === 0 ? navigate(-1) : setStep(STEPS[at - 1] as Step))}
        >
          {at === 0 ? t('common.action.cancel') : t('common.action.back')}
        </Button>
        {last ? (
          <Button
            size="lg"
            variant="agent"
            className="flex-[2]"
            disabled={!ready}
            loading={generate.isPending}
            onClick={submit}
          >
            <Icon name="agent" size={16} />
            {t('cards.generate.run.submit')}
          </Button>
        ) : (
          <Button size="lg" variant="primary" className="flex-[2]" onClick={() => setStep(STEPS[at + 1] as Step)}>
            {t('cards.generate.steps.next')}
          </Button>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-s3 rounded-md border border-line bg-surface p-s4 shadow-1">
      <h2 className="font-semibold text-ink-strong">{title}</h2>
      {children}
    </section>
  )
}

function BackLink({
  append,
  projectId,
  setId,
}: {
  append: boolean
  projectId: string | null
  setId: string | null
}) {
  const t = useT()
  return (
    <Button variant="ghost" asChild>
      <Link to={append ? `/cards/${projectId}/${setId}` : '/cards'}>
        <Icon name="arrowLeft" size={15} />
        {t(append ? 'cards.generate.toSet' : 'cards.generate.toLibrary')}
      </Link>
    </Button>
  )
}

/** Что уйдёт агенту — одной строкой перед запуском. */
function Summary({ form }: { form: Form }) {
  const t = useT()
  const parts: string[] = []
  if (form.topic.trim()) parts.push(form.topic.trim())
  const q = countQuestions(form.questions)
  if (q) parts.push(t('cards.generate.questions.count', { n: q }))
  if (form.materialIds.length) parts.push(t('cards.generate.run.files', { n: form.materialIds.length }))
  parts.push(t(form.perTopic ? 'cards.generate.run.cardsPerTopic' : 'cards.generate.run.cards', { n: form.count }))
  return <p className="text-sm text-ink">{parts.join(' · ')}</p>
}

/**
 * Сколько вопросов в списке: непустые строки, кроме строк-заголовков разделов.
 * Заголовок — строка с `#` в начале или строка, кончающаяся двоеточием.
 */
function countQuestions(text: string): number {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !/^#/.test(l) && !/:$/.test(l)).length
}
