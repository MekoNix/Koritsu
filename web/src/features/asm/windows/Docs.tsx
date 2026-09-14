/**
 * Docs — окно «Справка».
 *
 * Окно — обвязка `DocsView` вокруг состояния модуля: запрос «открыть справку на
 * записи» приходит из store (`docsRequest`, его кладёт `openDocs(token)` — F1,
 * контекстное меню, меню «Справка»), «Спросить агента» уходит в `askAgent` с
 * якорем записи, «Вставить пример» пишет в исходник.
 *
 * Пример вставляется **после строки под курсором**, а без курсора — в конец
 * через пустую строку: человек, открывший справку по F1 на строке кода, ждёт
 * пример рядом с этой строкой, а не за `end start`. Исходника ещё нет (программа
 * не загрузилась) — пример уходит в буфер обмена.
 */
import { useT } from '@/i18n'

import { DocsView } from '../docs/DocsView'
import type { DocEntry } from '../docs/entries'
import { useAsm } from '../store'
import type { AsmWindowProps } from '../types'

export default function Docs(_props: AsmWindowProps) {
  const t = useT()
  const { docsRequest, askAgent, program, setSource, cursorLine, toast } = useAsm()

  function insert(entry: DocEntry) {
    const ex = entry.ex
    if (!ex) return
    if (!program) {
      void copy(ex)
      return
    }
    const lines = program.source.split('\n')
    if (cursorLine !== null && cursorLine >= 1 && cursorLine <= lines.length) {
      lines.splice(cursorLine, 0, ...ex.split('\n'))
      setSource(lines.join('\n'))
      toast(t('asm.docs.insertedAfter', { line: cursorLine }))
    } else {
      const base = program.source.replace(/\s+$/, '')
      setSource(base ? `${base}\n\n${ex}\n` : `${ex}\n`)
      toast(t('asm.docs.insertedEnd'))
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast(t('asm.docs.copied'))
    } catch {
      toast(t('asm.docs.copyFailed'))
    }
  }

  return (
    <DocsView
      request={docsRequest}
      onAsk={(entry) => askAgent({ kind: 'doc', id: entry.id })}
      onInsert={insert}
    />
  )
}
