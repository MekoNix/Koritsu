/**
 * requests — то, что нужно заходу поверх общих запросов модуля (`../api.ts`).
 *
 * Здесь не хуки TanStack Query, а обычные функции: карточки подгружаются по
 * мере движения по очереди, и порядок запросов решает `usePlay`, а не кэш.
 *
 * **Карточки по ключам** (`?keys=`, до 100 за запрос, порядок как в запросе).
 * Заход идёт в своём порядке, а не по файлу, и страница `from/to` нужных
 * карточек не даёт.
 */
import { api, unwrap } from '@/api'

import { fetchSession } from '../api'
import type { CardAnswer, CardItem, CardSet, CardsPage, SessionAnswer, SessionState } from '../types'

export type Answer = CardAnswer

/** Сколько ключей уходит в один запрос `?keys=`. */
export const KEYS_PER_REQUEST = 100

/** Карточки по ключам, в порядке запроса. Ключа нет в наборе — карточки в ответе нет. */
export async function fetchCardsByKeys(projectId: string, setId: string, keys: readonly string[]): Promise<CardItem[]> {
  const raw = await unwrap<Partial<CardsPage>>(
    api.GET('/api/projects/{project_id}/cards/sets/{set_id}/cards', {
      params: { path: { project_id: projectId, set_id: setId }, query: { keys: keys.join(',') } },
    }),
  )
  return Array.isArray(raw.cards) ? raw.cards : []
}

/** Заход с тома, приведённый к одному виду. */
export async function fetchSessionState(projectId: string, sessionId: string): Promise<SessionState> {
  const raw = (await fetchSession(projectId, sessionId)) as Partial<SessionState> & { answers?: unknown }
  return {
    keys: Array.isArray(raw.keys) ? raw.keys : [],
    pos: typeof raw.pos === 'number' ? raw.pos : 0,
    answers: answersOf(raw.answers),
  }
}

function answersOf(raw: unknown): SessionAnswer[] {
  if (Array.isArray(raw)) {
    return raw
      .filter(
        (x): x is Partial<SessionAnswer> & Pick<SessionAnswer, 'key' | 'answer'> =>
          !!x && typeof x === 'object' && typeof x.key === 'string' && (x.answer === 'yes' || x.answer === 'no'),
      )
      .map((x) => ({
        key: x.key,
        answer: x.answer,
        shown: !!x.shown,
        ms: typeof x.ms === 'number' ? x.ms : 0,
        client_seq: typeof x.client_seq === 'number' ? x.client_seq : 0,
        corrects: typeof x.corrects === 'number' ? x.corrects : null,
      }))
  }
  return []
}

/** Повторять ли «Нет»: личная настройка, иначе рекомендуемая, иначе да. */
export function repeatWrongOf(set: Pick<CardSet, 'defaults' | 'my_settings'> | undefined): boolean {
  return set?.my_settings?.repeat_wrong ?? set?.defaults?.repeat_wrong ?? true
}
