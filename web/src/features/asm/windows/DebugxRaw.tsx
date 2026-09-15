/**
 * DebugxRaw — сырой вывод отладчика вокруг текущего шага: DebugX у TASM,
 * трассировщика у MinGW x64. Заголовок — по описателю режима (`titles.raw`).
 *
 * Всё, что показывают остальные окна, разобрано из этого текста. Когда
 * разобранное кажется странным, сверяться надо с первоисточником, поэтому он
 * доступен как есть — кусками по нескольку шагов: целиком он на порядок больше
 * самой трассы.
 */
import { useEffect, useRef, useState } from 'react'

import { useAsmRaw } from '@/features/asm/api'
import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'

import { fmtInt, hasTrace, useAnchorMenu, useSelectionAsk, veilText } from './format'

/** Сколько шагов до текущего показывать сразу. */
const BEFORE = 4
/** На сколько шагов расширяет «Показать раньше». */
const MORE = 20
/** Потолок куска по договору службы. */
const MAX_SPAN = 2000
/** Задержка после смены шага: удержанная F8 не должна слать запрос на каждый шаг. */
const SETTLE_MS = 250

export default function DebugxRaw({ active }: AsmWindowProps) {
  const t = useT()
  const { run, stepIndex, toolchain } = useAsm()
  const tasm = toolchain.id === 'tasm'
  /** Ветка строк окна: у TASM — прежние, у остальных режимов — трассировщика. */
  const k = tasm ? 'asm.debugx' : 'asm64.raw'
  const trace = hasTrace(run)
  const runNo = run?.run_no

  const [settled, setSettled] = useState(stepIndex)
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(stepIndex), SETTLE_MS)
    return () => window.clearTimeout(id)
  }, [stepIndex])

  const [extra, setExtra] = useState(0)
  useEffect(() => setExtra(0), [runNo])

  const to = settled + 1
  const from = Math.max(0, to - Math.min(MAX_SPAN, BEFORE + 1 + extra))

  // Скрытая вкладка и прогон без трассы кусков не просят: номер прогона не передаётся.
  const query = useAsmRaw(active && trace ? runNo : undefined, from, to)

  // Пока грузится следующий кусок, показываем прошлый, а не «загрузка» на каждый шаг.
  const shown = useRef<{ text: string; from: number; to: number } | null>(null)
  if (query.data) shown.current = { text: query.data.text, from, to }
  if (runNo == null || !trace) shown.current = null
  const data = shown.current

  const veil = veilText(run)
  const box = useRef<HTMLDivElement | null>(null)
  const menu = useAnchorMenu()
  const ask = useSelectionAsk({ window: 'debugx', active, root: box })

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t(toolchain.titles.raw)}>
      <div className="pt">
        <span className="m">{data ? t(`${k}.meta`, { from: fmtInt(data.from), to: fmtInt(data.to - 1) }) : ''}</span>
        <span className="grow" />
        {trace && from > 0 && (
          <button type="button" className="tb" onClick={() => setExtra((n) => n + MORE)}>
            {t('asm.debugx.more')}
          </button>
        )}
      </div>
      <div
        ref={box}
        className="qb"
        tabIndex={0}
        onContextMenu={(e) => {
          const text = ask.current()
          if (text) menu.open(e, text)
        }}
      >
        <div className="con">
          {veil ? (
            <span className="sys">{veil}</span>
          ) : query.isError && !data ? (
            <span className="sys err">{t(`${k}.error`)}</span>
          ) : !data ? (
            <span className="sys">{t(`${k}.loading`)}</span>
          ) : (
            <>
              {data.from > 0 && (
                <>
                  <span className="sys">{t('asm.debugx.above', { n: fmtInt(data.from) })}</span>
                  {'\n'}
                </>
              )}
              {data.text
                .replace(/\r\n?/g, '\n')
                .split('\n')
                .map((line, i) => (
                  <span key={i} className={(tasm ? /^-[a-z]/i : /^=>/).test(line) ? 'cmd' : undefined}>
                    {line}
                    {'\n'}
                  </span>
                ))}
            </>
          )}
        </div>
      </div>
      {ask.element}
      {menu.element}
    </section>
  )
}
