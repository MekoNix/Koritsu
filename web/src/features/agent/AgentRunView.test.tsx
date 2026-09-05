/**
 * Проверка того, как нарисован ход работы и итог.
 *
 * Отдельно от браузерной проверки намеренно: поддельная модель стенда
 * инструментов не зовёт (это её решение, `web/e2e/fake-llm/server.py`), и
 * событий `tag_closed` в настоящем прогоне на стенде не бывает вовсе. Значит
 * ходы и ссылки на изменённые теги можно проверить только здесь — на кадрах,
 * собранных руками по форме службы.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { AgentRunView } from './AgentRunView'
import type { AgentRunState } from './useAgentRun'

function прогон(над: Partial<AgentRunState> = {}): AgentRunState {
  return {
    job: {
      id: 'j-1',
      kind: 'agent',
      status: 'done',
      project_id: 'p-1',
      result: null,
      error: null,
      created_at: '2026-09-05T01:00:00+00:00',
    },
    running: false,
    starting: false,
    moves: [
      { seq: 4, key: 'теория' },
      { seq: 5, key: 'вывод' },
    ],
    text: 'Разобрал проект и заполнил два тега.',
    step: 7,
    total: 7,
    limitExhausted: false,
    result: { filled: ['теория', 'вывод'], steps: 7, calls: 11, outcome: 'done', ok: true },
    changed: ['теория', 'вывод'],
    lastTask: 'перепиши введение короче',
    startError: null,
    start: () => {},
    regenerate: () => {},
    cancel: () => {},
    ...над,
  }
}

function нарисовать(run: AgentRunState) {
  return render(
    <MemoryRouter>
      <AgentRunView run={run} projectId="p-1" />
    </MemoryRouter>,
  )
}

describe('AgentRunView', () => {
  it('показывает ходы, текст и изменённые теги ссылками', () => {
    нарисовать(прогон())

    // Ход — поставленный тег; ссылка ведёт на него же в отчёте.
    const ходы = screen.getAllByRole('link', { name: /теория/ })
    expect(ходы.length).toBeGreaterThan(0)
    expect(ходы[0]).toHaveAttribute('href', '/reports/p-1?tag=%D1%82%D0%B5%D0%BE%D1%80%D0%B8%D1%8F')

    expect(screen.getByText('Разобрал проект и заполнил два тега.')).toBeInTheDocument()
    expect(screen.getByText('Что изменилось')).toBeInTheDocument()
    expect(screen.getByText('ходов: 7 · вызовов модели: 11')).toBeInTheDocument()
  })

  it('пока прогон идёт, итога не показывает', () => {
    нарисовать(
      прогон({
        running: true,
        job: {
          id: 'j-1',
          kind: 'agent',
          status: 'running',
          project_id: 'p-1',
          result: null,
          error: null,
          created_at: '2026-09-05T01:00:00+00:00',
        },
      }),
    )
    expect(screen.queryByText('Что изменилось')).toBeNull()
    expect(screen.getByText('работает')).toBeInTheDocument()
  })

  it('не выдаёт неудачный прогон за пустой', () => {
    // Уровень 3 отдаёт `done` даже когда модель не ответила: у задания это
    // штатный конец, у прогона — нет (`ok: false`). Оболочка про такой случай
    // не тостит, и сказать о нём обязана панель.
    нарисовать(
      прогон({
        result: { filled: [], ok: false, outcome: 'error', steps: 1, calls: 0 },
        changed: [],
        moves: [],
      }),
    )
    expect(screen.getByText(/Прогон дошёл не до конца/)).toBeInTheDocument()
    expect(screen.getByText(/модель не ответила/)).toBeInTheDocument()
  })

  it('называет причину упавшего прогона по коду задания', () => {
    нарисовать(
      прогон({
        job: {
          id: 'j-1',
          kind: 'agent',
          status: 'failed',
          project_id: 'p-1',
          result: null,
          error: { code: 'agent_refused', message: 'nothing to fill' },
          created_at: '2026-09-05T01:00:00+00:00',
        },
        result: null,
        changed: [],
      }),
    )
    expect(screen.getByText(/Агент отказался выполнять задание/)).toBeInTheDocument()
    // Итога у упавшего прогона нет: показывать «изменилось ноль тегов» там,
    // где задание не доработало, значит утверждать неправду.
    expect(screen.queryByText('Что изменилось')).toBeNull()
  })

  it('говорит словами про кончившийся месячный остаток', () => {
    нарисовать(прогон({ limitExhausted: true }))
    expect(screen.getByText(/Месячный остаток кончился/)).toBeInTheDocument()
  })
})
