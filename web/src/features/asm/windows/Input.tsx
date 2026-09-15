/**
 * Input — ввод программы и параметры запуска: stdin, лимит шагов, 16/32 бит.
 *
 * Паузы на вводе в прогоне нет: трасса пишется целиком за один запуск, и всё,
 * что программа прочитает функциями DOS, задаётся здесь заранее. Поэтому окно
 * показывает не только текст, но и что из него уже прочитано к текущему шагу:
 * «почему AL = 0Dh» почти всегда значит «ввод кончился раньше, чем программа
 * перестала читать».
 *
 * Правка ввода не меняет уже записанную трассу — она учтётся в следующем
 * прогоне, и окно об этом говорит.
 */
import { useEffect, useRef, useState } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button } from '@/ui'

import { fmtInt, hasTrace, useTraceScan, visibleChar } from './format'

const LIMIT_MIN = 1_000
const LIMIT_MAX = 500_000
/** Сколько символов ввода рисовать клетками. */
const CHARS_SHOWN = 80
/** Задержка сохранения ввода после последнего нажатия, мс. */
const SAVE_DELAY_MS = 400

export default function Input({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, stepIndex, settings, view, runBusy, toolchain } = asm
  const tasm = toolchain.id === 'tasm'
  const scan = useTraceScan('current', active)
  const trace = hasTrace(run)

  const [draft, setDraft] = useState(settings.stdin)
  const [limit, setLimit] = useState(String(settings.step_limit))
  const editing = useRef(false)
  // Сохранение держим ссылкой: таймер не должен сбрасываться каждой
  // перерисовкой, которую вызывает сам store.
  const update = useRef(asm.updateSettings)
  update.current = asm.updateSettings

  useEffect(() => {
    if (!editing.current) setDraft(settings.stdin)
  }, [settings.stdin])

  useEffect(() => {
    setLimit(String(settings.step_limit))
  }, [settings.step_limit])

  useEffect(() => {
    if (draft === settings.stdin) return
    const id = window.setTimeout(() => update.current({ stdin: draft }), SAVE_DELAY_MS)
    return () => window.clearTimeout(id)
  }, [draft, settings.stdin])

  const commitLimit = () => {
    const n = parseInt(limit.replace(/\s/g, ''), 10)
    const v = Number.isFinite(n) ? Math.max(LIMIT_MIN, Math.min(LIMIT_MAX, n)) : settings.step_limit
    setLimit(String(v))
    if (v !== settings.step_limit) asm.updateSettings({ step_limit: v })
  }

  const setBits = (bits: 16 | 32) => {
    asm.setView({ bits })
    if (settings.mode32 !== (bits === 32)) asm.updateSettings({ mode32: bits === 32 })
  }

  const source = trace && run ? run.stdin : draft
  const chars = [...source]
  const read = trace ? (step?.stdin_pos ?? 0) : 0
  const dirty = trace && !!run && draft !== run.stdin

  let hint: string
  if (trace) {
    hint = t('asm.input.hintRead', { step: fmtInt(stepIndex), read: Math.min(read, chars.length), total: chars.length })
    if (read > chars.length) hint += ' ' + t(tasm ? 'asm.input.hintOver' : 'asm64.input.hintOver', { n: read - chars.length })
    const nextAt = scan?.reads[read]
    if (read < chars.length && nextAt != null) hint += ' ' + t('asm.input.hintNext', { step: fmtInt(nextAt) })
  } else hint = t('asm.input.noTrace')

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.input')}>
      <div className="pt">
        <span className="m">{trace && run ? t('asm.input.meta', { read, limit: fmtInt(run.step_limit) }) : ''}</span>
      </div>
      <div className="inp">
        <div className="fld">
          <label htmlFor="asm-stdin">{t(tasm ? 'asm.input.stdinLabel' : 'asm64.input.stdinLabel')}</label>
          <textarea
            id="asm-stdin"
            rows={3}
            value={draft}
            spellCheck={false}
            autoComplete="off"
            onFocus={() => {
              editing.current = true
            }}
            onBlur={() => {
              editing.current = false
              if (draft !== settings.stdin) asm.updateSettings({ stdin: draft })
            }}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
        <div className="chars" aria-label={t('asm.input.charsLabel')}>
          {chars.length === 0 ? (
            <span>{t('asm.input.emptyChars')}</span>
          ) : (
            chars.slice(0, CHARS_SHOWN).map((c, i) => {
              const at = scan?.reads[i]
              // Вызов чтения забирает строку целиком: клетка подписана шагом вызова и функцией.
              const call = !tasm && at != null ? asm.getStep(at)?.call : null
              const readTitle = at == null ? t('asm.input.readDone') : call ? t('asm64.input.readAtCall', { step: fmtInt(at), call }) : t('asm.input.readAt', { step: fmtInt(at) })
              return (
                <span
                  key={i}
                  className={cn(i < read && 'rd', trace && i === read && 'nx')}
                  title={i < read ? readTitle : t('asm.input.notRead')}
                >
                  {visibleChar(c)}
                </span>
              )
            })
          )}
          {chars.length > CHARS_SHOWN && <span>+{chars.length - CHARS_SHOWN}</span>}
        </div>
        <div className="hint">
          {hint}
          {dirty && <span className="dirty"> {t('asm.input.dirty')}</span>}
        </div>
        {!tasm && source.includes('\n') && <div className="hint">{t('asm64.input.crlf')}</div>}
        <div className="row">
          <div className="fld">
            <label htmlFor="asm-step-limit">{t('asm.input.limitLabel')}</label>
            <input
              id="asm-step-limit"
              type="number"
              min={LIMIT_MIN}
              max={LIMIT_MAX}
              step={1000}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              onBlur={commitLimit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitLimit()
              }}
            />
          </div>
          {toolchain.bitsSwitch && (
            <div className="fld">
              <span className="lbl-s">{t('asm.input.bitsLabel')}</span>
              <div className="seg" role="group" aria-label={t('asm.input.bitsLabel')}>
                {([16, 32] as const).map((b) => (
                  <button key={b} type="button" aria-pressed={view.bits === b} onClick={() => setBits(b)}>
                    {b === 16 ? t('asm.input.bits16') : t('asm.input.bits32')}
                  </button>
                ))}
              </div>
            </div>
          )}
          <span className="grow" />
          <Button
            variant="primary"
            size="sm"
            loading={runBusy}
            onClick={() => {
              if (draft !== settings.stdin) asm.updateSettings({ stdin: draft })
              asm.buildAndRun()
            }}
          >
            {t('asm.input.run')}
          </Button>
        </div>
        {toolchain.bitsSwitch && view.bits === 32 && trace && run && !run.mode32 && <div className="hint dirty">{t('asm.input.no32')}</div>}
      </div>
    </section>
  )
}
