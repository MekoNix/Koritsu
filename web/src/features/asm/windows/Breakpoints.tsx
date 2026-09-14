/**
 * Breakpoints — список точек останова: строка, её текст, сколько раз она
 * выполнялась.
 *
 * Точки — номера строк исходника и хранятся в параметрах программы: их ставят
 * в «Исходнике», «Листинге» и клавишей F2, а здесь видят все сразу. Щелчок по
 * строке ставит на неё курсор — «Листинг» и «Исходник» сами к нему прокрутятся.
 */
import { useMemo } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { fmtInt, lastStepIndex, sameAnchor, useAnchorMenu, useTraceScan } from './format'
import { mnemonicOf, tasmSpans } from './tasmLanguage'

/** До скольких шагов счётчик считается за весь прогон (как в «Листинге»). */
const HITS_FULL_LIMIT = 20_000

export default function Breakpoints({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, program, settings, selection } = asm
  const menu = useAnchorMenu()
  const scan = useTraceScan(lastStepIndex(run) <= HITS_FULL_LIMIT ? 'end' : 'current', active)
  const lines = useMemo(() => (program?.source ?? '').split('\n'), [program?.source])
  const list = useMemo(() => [...settings.breakpoints].sort((a, b) => a - b), [settings.breakpoints])

  const go = (line: number) => {
    asm.setCursorLine(line)
    asm.select({ kind: 'line', line })
  }

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.breakpoints')}>
      <div className="pt">
        <span>{t('asm.breakpoints.hint')}</span>
        <span className="grow" />
        <button type="button" className="tb" disabled={list.length === 0} onClick={() => asm.updateSettings({ breakpoints: [] })}>
          {t('asm.breakpoints.clear')}
        </button>
      </div>
      <div className="qb">
        {list.length === 0 ? (
          <div className="empty">{t('asm.breakpoints.empty')}</div>
        ) : (
          list.map((line) => {
            const text = (lines[line - 1] ?? '').replace(/\r$/, '')
            const hits = scan?.hits.get(line)
            return (
              <div
                key={line}
                role="button"
                tabIndex={0}
                className={cn('bpr', sameAnchor(selection, { kind: 'line', line }) && 'is-ctx')}
                onClick={() => go(line)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter' && e.key !== ' ') return
                  e.preventDefault()
                  go(line)
                }}
                onContextMenu={(e) => menu.open(e, { kind: 'line', line }, mnemonicOf(text))}
              >
                <i />
                <span className="bl">{t('asm.breakpoints.line', { line })}</span>
                <span className="bs">{line > lines.length ? t('asm.breakpoints.gone') : tasmSpans(text.trim())}</span>
                <span className="bh">{hits ? `×${fmtInt(hits)}` : ''}</span>
                <button
                  type="button"
                  className="x"
                  aria-label={t('asm.breakpoints.remove', { line })}
                  onClick={(e) => {
                    e.stopPropagation()
                    asm.updateSettings({ breakpoints: settings.breakpoints.filter((l) => l !== line) })
                  }}
                >
                  ×
                </button>
              </div>
            )
          })
        )}
      </div>
      {menu.element}
    </section>
  )
}
