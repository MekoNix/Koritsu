/**
 * BoardErrorBoundary — сбой одного компонента доски не гасит весь экран.
 *
 * Без границы исключение из эффекта любого потомка (поле формулы, холст)
 * снимает с экрана всё дерево, и человек видит пустую страницу без единого
 * слова — это неотличимо от «сайт упал». Здесь он видит, что именно не
 * поднялось, и может перезагрузить страницу; холст и чистовик при этом уже
 * сохранены службой, терять нечего.
 */
import { Component, type ReactNode } from 'react'

import { t } from '@/i18n'
import { Button } from '@/ui'

type State = { error: string | null }

export class BoardErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null }

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error.message : String(error) }
  }

  override render() {
    if (this.state.error === null) return this.props.children
    return (
      <section className="m-s4 flex flex-col gap-s2 rounded-md border border-err bg-err-bg p-s3 text-sm">
        <p className="font-semibold text-err">{t('board.crash.title')}</p>
        <p className="text-xs text-ink">{t('board.crash.hint')}</p>
        <pre className="max-h-[160px] overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-surface-2 p-s2 font-mono text-xs text-ink">
          {this.state.error}
        </pre>
        <div>
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            {t('board.crash.reload')}
          </Button>
        </div>
      </section>
    )
  }
}
