/**
 * paths — адреса экранов «Тренажёра» одним местом.
 *
 *     /cards                              библиотека пространства
 *     /cards/new[?sample=1]               загрузка файла или текста; `sample` — пример набора
 *     /cards/generate[?project=&set=]     создание агентом; с `project`+`set` — дополнить набор
 *     /cards/drafts/:draftId              черновик
 *     /cards/:projectId/:setId            набор
 *     /cards/:projectId/:setId/play?s=    заход и итоги
 *
 * Страница набора, заводя заход, передаёт его на экран захода двумя путями: номер —
 * в `?s=` (переживает перезагрузку), ответ службы целиком — в состоянии перехода
 * (`PlayLocationState.start`), чтобы первая карточка показалась без второго запроса.
 */
import type { SessionStart } from './types'

const e = encodeURIComponent

export const cardsPaths = {
  library: '/cards',
  upload: '/cards/new',
  sample: '/cards/new?sample=1',
  set: (projectId: string, setId: string) => `/cards/${e(projectId)}/${e(setId)}`,
  play: (projectId: string, setId: string, sessionId?: string) =>
    `/cards/${e(projectId)}/${e(setId)}/play${sessionId ? `?s=${e(sessionId)}` : ''}`,
  generate: (target?: { projectId: string; setId: string }) =>
    target ? `/cards/generate?project=${e(target.projectId)}&set=${e(target.setId)}` : '/cards/generate',
  draft: (draftId: string) => `/cards/drafts/${e(draftId)}`,
}

/** Состояние перехода на экран захода. */
export interface PlayLocationState {
  /** Ответ `POST …/sessions`. */
  start?: SessionStart
}
