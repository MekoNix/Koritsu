/**
 * UploadPage — загрузка набора: файл `.json`, `.csv`, `.tsv` или вставленный текст.
 *
 *     /cards/new            пустая форма
 *     /cards/new?sample=1   пример набора: текст примера сразу в поле и в проверке
 *
 * **Два шага.** Сначала проверка (`POST /api/cards/preview`): служба разбирает текст
 * в черновик и отдаёт проблемы с местом (карточка и поле по пути JSON, строка и
 * столбец у битого JSON), число карточек и тем. Набор создаётся вторым
 * нажатием из этого черновика. Частичного импорта молча нет: файл без проблем создаётся
 * целиком, файл с проблемами карточек — только явным «Создать только годные (N из M)».
 * Проблема всего файла (например, файл не разобрался) не даёт создать ничего.
 *
 * **Две раскладки.** На компьютере — источник слева, итог проверки справа. На телефоне
 * — одна колонка: системный выбор файла или вставка текста, итог ниже, а кнопка
 * «Создать» закреплена внизу экрана под большим пальцем, с отступом `safe-area`.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { BetaTag, Button, Chip, EmptyState, ErrorState, Icon, SkeletonLines } from '@/ui'
import { canEditWorkspace } from '@/features/projects/data'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { AGENT_TEMPLATE } from './agentTemplate'
import { useCreateCardSet, usePreviewCards, type CardsSource } from './api'
import { ProblemsTable } from './components/ProblemsTable'
import { SourcePicker } from './components/SourcePicker'
import { useIsPhone } from './hooks/useIsPhone'
import { cardsPaths } from './paths'
import { hasSample, loadSample } from './samples'
import { hasFileProblems, validOf } from './types'

export function UploadPage() {
  const t = useT()
  const navigate = useNavigate()
  const isPhone = useIsPhone()
  const [params] = useSearchParams()
  const workspace = useCurrentWorkspace()
  const preview = usePreviewCards()
  const create = useCreateCardSet()
  useDocumentCrumb(t('cards.upload.title'))

  const хочуПример = params.get('sample') === '1'
  const [пример, setПример] = useState<CardsSource | null>(null)
  const [примераНет, setПримераНет] = useState(false)
  const [источник, setИсточник] = useState<CardsSource | null>(null)
  const { mutate: проверить } = preview

  useEffect(() => {
    if (!хочуПример) return
    if (!hasSample) {
      setПримераНет(true)
      return
    }
    let живо = true
    loadSample().then(
      (s) => {
        if (!живо) return
        setПример(s)
        setИсточник(s)
        проверить(s)
      },
      () => живо && setПримераНет(true),
    )
    return () => {
      живо = false
    }
  }, [хочуПример, проверить])

  const проверитьИсточник = (s: CardsSource) => {
    setИсточник(s)
    проверить(s)
  }

  const canEdit = canEditWorkspace(workspace.data?.role)

  const шапка = (
    <header className="flex min-w-0 flex-col gap-s2">
      <Link to={cardsPaths.library} className="inline-flex min-h-[44px] items-center gap-1 self-start text-sm text-muted min-[641px]:min-h-0">
        <Icon name="arrowLeft" size={16} />
        {t('cards.common.back')}
      </Link>
      <div className="min-w-0">
        <WorkspaceCaption ws={workspace.data} className="mb-1" />
        <h1 className="m-0 flex items-center gap-s2 font-display text-2xl font-semibold text-ink-strong max-[640px]:text-xl">
          {t('cards.upload.title')}
          <BetaTag label={t('shell.beta')} />
        </h1>
        <p className="m-0 max-w-[64ch] text-sm text-muted">{t('cards.upload.subtitle')}</p>
      </div>
    </header>
  )

  if (workspace.isPending) {
    return (
      <div className="flex flex-col gap-s5">
        {шапка}
        <SkeletonLines count={4} />
      </div>
    )
  }
  if (!canEdit) {
    return (
      <div className="flex flex-col gap-s5">
        {шапка}
        <EmptyState icon="user" title={t('cards.common.forbidden')} />
      </div>
    )
  }

  const итог = preview.data
  const проблемы = итог?.problems ?? []
  const числа = validOf(итог?.stats)
  const файловые = hasFileProblems(проблемы)
  const готово = !!итог && !preview.isPending
  const можноВсё = готово && проблемы.length === 0 && (итог?.stats.cards ?? 0) > 0
  const можноГодные = готово && проблемы.length > 0 && !файловые && (числа ? числа.valid > 0 : true)

  const создать = (onlyValid: boolean) => {
    const ws = workspace.data?.id
    if (!ws || !итог) return
    create.mutate(
      { workspace_id: ws, draft_id: итог.draft_id, ...(onlyValid ? { only_valid: true } : {}) },
      { onSuccess: (r) => navigate(cardsPaths.set(r.project_id, r.set_id), { replace: true }) },
    )
  }

  const кнопка = можноВсё ? (
    <Button variant="primary" size={isPhone ? 'lg' : 'md'} loading={create.isPending} onClick={() => создать(false)} className="max-[640px]:w-full">
      <Icon name="plus" size={16} />
      {t('cards.upload.create')}
    </Button>
  ) : можноГодные ? (
    <Button variant="primary" size={isPhone ? 'lg' : 'md'} loading={create.isPending} onClick={() => создать(true)} className="max-[640px]:w-full">
      <Icon name="plus" size={16} />
      {числа ? t('cards.upload.createValid', { valid: числа.valid, total: числа.total }) : t('cards.upload.createValidShort')}
    </Button>
  ) : null

  return (
    <div className="flex flex-col gap-s5">
      {шапка}

      <div className="grid items-start gap-s5 min-[961px]:grid-cols-2">
        <section className="flex min-w-0 flex-col gap-s4">
          {хочуПример && !пример && !примераНет ? (
            <SkeletonLines count={3} />
          ) : (
            <SourcePicker
              key={пример ? 'sample' : 'own'}
              initialText={пример?.text}
              initialFilename={пример?.filename}
              busy={preview.isPending}
              onSource={проверитьИсточник}
            />
          )}
          {примераНет && <p className="m-0 text-sm text-warn">{t('cards.upload.sampleMissing')}</p>}
          <FormatNotes />
          <AgentTemplate />
        </section>

        <section aria-live="polite" aria-label={t('cards.upload.result')} className="flex min-w-0 flex-col gap-s3">
          {preview.isPending ? (
            <SkeletonLines count={4} />
          ) : preview.isError ? (
            <ErrorState
              error={preview.error}
              onRetry={источник ? () => проверить(источник) : undefined}
            />
          ) : итог ? (
            <div className="flex min-w-0 flex-col gap-s3 rounded-md border border-line bg-surface p-s4 shadow-1">
              <div className="flex flex-wrap items-center gap-s2">
                <Chip tone={проблемы.length ? 'warn' : 'ok'}>
                  {проблемы.length ? t('cards.upload.problems', { n: проблемы.length }) : t('cards.upload.ok')}
                </Chip>
                <span className="text-sm text-ink">
                  {t('cards.common.cardsCount', { n: итог.stats.cards })} · {t('cards.common.topicsCount', { n: итог.stats.topics })}
                </span>
              </div>
              {проблемы.length > 0 && (
                <p className={файловые ? 'm-0 text-sm text-err' : 'm-0 text-sm text-muted'}>
                  {файловые ? t('cards.upload.fileProblems') : числа?.valid === 0 ? t('cards.upload.noneValid') : t('cards.upload.fixHint')}
                </p>
              )}
              {проблемы.length === 0 && итог.stats.cards === 0 && <p className="m-0 text-sm text-muted">{t('cards.upload.noCards')}</p>}
              <ProblemsTable problems={проблемы} />
              {create.isError && <p className="m-0 text-sm text-err">{errorText(create.error)}</p>}
              {!isPhone && кнопка && <div className="flex justify-end">{кнопка}</div>}
            </div>
          ) : (
            !isPhone && <EmptyState compact icon="file" title={t('cards.upload.resultEmpty')} text={t('cards.upload.resultEmptyText')} />
          )}
        </section>
      </div>

      {isPhone && кнопка && (
        <div className="sticky bottom-0 z-10 -mx-s3 -mb-s3 border-t border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] px-s3 pt-s2 pb-[max(env(safe-area-inset-bottom),var(--space-2))] backdrop-blur-theme">
          {кнопка}
        </div>
      )}
    </div>
  )
}

/**
 * Шаблон запроса к модели — целиком в буфер обмена.
 *
 * Не свёрнут, в отличие от справки по формату: набор чаще начинается не с
 * готового файла, а со списка вопросов к экзамену, и этот список кто-то должен
 * перевести в формат. Кнопка копирует текст, который остаётся дописать своими
 * вопросами и отдать любой модели.
 */
function AgentTemplate() {
  const t = useT()
  const [скопировано, setСкопировано] = useState(false)

  async function копировать() {
    try {
      await navigator.clipboard.writeText(AGENT_TEMPLATE)
    } catch {
      // Буфер обмена запрещён — текст остаётся в документации формата.
      return
    }
    setСкопировано(true)
    window.setTimeout(() => setСкопировано(false), 1500)
  }

  return (
    <section className="flex min-w-0 flex-col gap-s2 rounded-md border border-line bg-surface p-s4">
      <h2 className="m-0 text-sm font-semibold text-ink">{t('cards.upload.templateTitle')}</h2>
      <p className="m-0 text-sm text-muted">{t('cards.upload.templateText')}</p>
      <Button type="button" variant="secondary" className="self-start" onClick={() => void копировать()}>
        <Icon name={скопировано ? 'check' : 'copy'} size={16} />
        {скопировано ? t('common.action.copied') : t('cards.upload.templateCopy')}
      </Button>
    </section>
  )
}

/** Полное описание формата — в репозитории проекта. */
const FORMAT_DOC_URL = 'https://github.com/MekoNix/Koritsu/blob/main/docs/cards-format.md'

/** Короткая справка по формату — свёрнутой, чтобы не мешать тем, кто его знает. */
function FormatNotes() {
  const t = useT()
  return (
    <details className="rounded-md border border-line bg-surface px-s4">
      <summary className="flex min-h-[44px] cursor-pointer items-center text-sm font-medium text-ink">{t('cards.upload.formatTitle')}</summary>
      <div className="flex min-w-0 flex-col gap-s2 pb-s4 text-sm text-muted">
        <p className="m-0">{t('cards.upload.formatText')}</p>
        <pre className="m-0 max-w-full overflow-x-auto rounded-sm bg-surface-2 p-s3 font-mono text-xs leading-snug text-ink">
          {t('cards.upload.formatExample')}
        </pre>
        <p className="m-0">{t('cards.upload.formatEscape')}</p>
        <p className="m-0">{t('cards.upload.csvText')}</p>
        <a
          href={FORMAT_DOC_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex min-h-[44px] items-center gap-1 self-start text-accent underline min-[641px]:min-h-0"
        >
          {t('cards.upload.formatLink')}
        </a>
      </div>
    </details>
  )
}
