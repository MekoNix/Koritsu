/**
 * AsmPage — экран программы: «CPU-окно» в духе Turbo Debugger.
 *
 *     строка меню · крошки · ▶ Собрать и запустить · статус
 *     ползунок трассы (окно отладчика)
 *     док окон
 *     строка клавиш (окно отладчика)
 *
 * Страница — оболочка: программу читает она, всё остальное — `AsmProvider`
 * (состояние), `Dock` (раскладка), `MenuBar` (меню), окна из `windows/`. Экран
 * во всю ширину (`useWidePage`): у отладчика четыре окна в два ряда, и поля
 * колонки текста отнимали бы у самого узкого — регистров — половину цифр.
 *
 * **Общей панели агента на этом экране нет** — у программы свой агент окном
 * дока, со своим заданием и контекстом трассы; Ctrl+J здесь открывает его.
 */
import { Suspense, lazy } from 'react'
import { useParams } from 'react-router-dom'

import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useWidePage } from '@/app/shell/widePage'
import { useT } from '@/i18n'
import { ErrorState, SkeletonLines } from '@/ui'

import { AsmAddressContext, useAsmProgram } from './api'
import { Dock } from './dock/Dock'
import { useAsmHotkeys } from './hotkeys'
import { AsmDialogs } from './menu/dialogs'
import { MenuBar } from './menu/MenuBar'
import { AsmProvider, useAsm, useAsmUi } from './store'
import './styles.css'

const TraceSlider = lazy(() => import('./windows/TraceSlider'))
const KeyBar = lazy(() => import('./windows/KeyBar'))

export function AsmPage() {
  const { projectId = '', programId = '' } = useParams()
  useWidePage()
  const program = useAsmProgram(projectId, programId, { fresh: true })
  useDocumentCrumb(program.data?.name)

  // Программа из кэша прошлого открытия — не начальное значение редактора:
  // ждём ответа тома (см. `useAsmProgram`).
  if (program.isPending || (!program.isError && !program.isFetchedAfterMount)) {
    return (
      <div className="p-s4">
        <SkeletonLines count={6} />
      </div>
    )
  }
  if (program.isError) return <ErrorState error={program.error} onRetry={() => void program.refetch()} />

  return (
    <AsmAddressContext.Provider value={{ projectId, programId }}>
      <AsmProvider key={`${projectId}/${programId}`} projectId={projectId} programId={programId} program={program.data}>
        <AsmScreen />
      </AsmProvider>
    </AsmAddressContext.Provider>
  )
}

function AsmScreen() {
  useAsmHotkeys()
  const asm = useAsm()
  const ui = useAsmUi()

  return (
    <div className="asm" data-busy={asm.runBusy || undefined}>
      <MenuBar />
      <SaveBars />
      {asm.view.traceSlider && (
        <Suspense fallback={<div className="asm-scrub-wait" />}>
          <TraceSlider />
        </Suspense>
      )}
      <Dock />
      {asm.view.keyBar && (
        <Suspense fallback={null}>
          <KeyBar />
        </Suspense>
      )}
      <AsmDialogs />
      <div className="asm-notice" role="status" aria-live="polite" hidden={!ui.notice}>
        {ui.notice?.text}
      </div>
    </div>
  )
}

/** Полосы о записи: чужая версия исходника (409), отказ записи исходника или настроек. */
function SaveBars() {
  const t = useT()
  const ui = useAsmUi()
  if (ui.saveState === 'conflict') {
    return (
      <div className="asm-bar is-warn" role="alert">
        <span>{t('asm.save.conflictText')}</span>
        <span className="grow" />
        <button type="button" disabled={!ui.conflict} onClick={() => ui.resolveConflict('theirs')}>
          {t('asm.save.takeTheirs')}
        </button>
        <button type="button" disabled={!ui.conflict} onClick={() => ui.resolveConflict('mine')}>
          {t('asm.save.keepMine')}
        </button>
      </div>
    )
  }
  if (ui.saveState === 'error') {
    return (
      <div className="asm-bar is-err" role="alert">
        <span>{t('asm.save.errorText', { reason: ui.saveError ?? '' })}</span>
        <span className="grow" />
        <button type="button" onClick={() => void ui.flush()}>
          {t('asm.save.retry')}
        </button>
      </div>
    )
  }
  if (ui.settingsError) {
    return (
      <div className="asm-bar is-err" role="alert">
        <span>{t('asm.save.settingsErrorText', { reason: ui.settingsError })}</span>
        <span className="grow" />
        <button type="button" onClick={() => void ui.flush()}>
          {t('asm.save.retry')}
        </button>
      </div>
    )
  }
  return null
}
