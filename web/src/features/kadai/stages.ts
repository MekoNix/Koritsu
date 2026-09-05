/**
 * stages — чистая часть области «Задания»: разбор стадий, событий и payload.
 *
 * Отдельным файлом без React, потому что здесь три правила, каждое из которых
 * ошибается молча, и проверяются они тестом, а не глазами:
 *
 * 1. **Живой ход стадий склеивается из двух источников.** Служба отдаёт снимок
 *    работы (`GET …/kadai`, состояния всех семи стадий), а прогон присылает
 *    события `stage` по мере хода. Снимок в это время устаревает: перечитывать
 *    его на каждое событие значило бы гнать запрос раз в секунду ради того, что
 *    уже приехало в потоке. Поэтому события накладываются на снимок.
 * 2. **Порядок стадий задаёт служба** (`GET /api/kadai/stages`), а не браузер.
 *    Своя копия списка отстала бы от пакета молча — восьмая стадия появилась бы
 *    в службе и не появилась бы на экране. Пока список не приехал, порядок
 *    берётся из снимка: он тот же самый.
 * 3. **Пожелания уезжают только в первый прогон.** Служба заводит работу один
 *    раз (`orchestrator.kadai.work`: есть запись — продолжаем, нет — заводим), и
 *    пожелания второго прогона она молча выбрасывает. Класть их в payload
 *    продолжения значило бы показать человеку поле, которое ни на что не влияет.
 */

/** Состояния стадии — так, как их пишет `kadai.stages`. Значения по-русски. */
export const WAITING = 'ждёт'
export const RUNNING = 'идёт'
export const DONE = 'сделано'
export const STUMBLED = 'споткнулась'
export const SKIPPED = 'пропущена'

/** Состояния работы целиком (`kadai.stages.WORK_STATES`). Ключи латиницей. */
export type WorkState = 'running' | 'waiting_user' | 'done' | 'failed' | 'cancelled'

export type StageState = {
  name: string
  state: string
  note?: string | null
  progress?: { done: number; total: number; unit?: string } | null
}

/** Событие `stage` из потока задания: имя стадии и её новое состояние. */
export type StageEvent = { name?: unknown; state?: unknown; note?: unknown }

/**
 * Стадии для полоски шагов: имена от службы, состояния от снимка и потока.
 *
 * `names` пустые — берём порядок из снимка. Стадия, которой в снимке нет
 * вовсе (работу ещё не заводили), показывается как «ждёт»: это правда, а не
 * заглушка, и она отличима от «пропущена».
 */
export function mergeStages(
  names: string[],
  snapshot: StageState[] | undefined,
  events: StageEvent[],
): StageState[] {
  const из_снимка = new Map((snapshot ?? []).map((s) => [s.name, s]))
  const порядок = names.length > 0 ? names : (snapshot ?? []).map((s) => s.name)
  const из_потока = new Map<string, string>()
  for (const событие of events) {
    if (typeof событие.name === 'string' && typeof событие.state === 'string') {
      из_потока.set(событие.name, событие.state)
    }
  }
  return порядок.map((name) => {
    const было = из_снимка.get(name)
    const свежее = из_потока.get(name)
    return {
      name,
      state: свежее ?? было?.state ?? WAITING,
      note: было?.note ?? null,
      progress: было?.progress ?? null,
    }
  })
}

/** Стадия, которая идёт прямо сейчас, или `null`. */
export function currentStage(stages: StageState[]): string | null {
  const идёт = stages.find((s) => s.state === RUNNING)
  if (идёт) return идёт.name
  // Прогон между стадиями: первая, до которой ещё не дошли.
  const следующая = stages.find((s) => s.state === WAITING)
  return следующая ? следующая.name : null
}

/** Пройдена ли стадия: сделана или пропущена (у пропущенной делать нечего). */
export function passed(state: string): boolean {
  return state === DONE || state === SKIPPED
}

/** Дошла ли работа до этой стадии. По ней решается, есть ли уже что показывать. */
export function reached(stages: StageState[], name: string): boolean {
  return stages.some((s) => s.name === name && passed(s.state))
}

export type Wishes = { text: string; show_task: boolean; show_structure: boolean }

export type RunPayload = {
  endpoint: string
  until?: string
  wishes?: Wishes
}

/**
 * Тело задания `kadai_run`.
 *
 * `until` кладётся только когда просят остановиться раньше конца: пустая
 * строка и последняя стадия — это одно и то же «пройти всё», а лишний ключ в
 * payload службе пришлось бы проверять на имя стадии (`unknown_stage`).
 *
 * `wishes` — только в первый прогон (правило 3 в шапке файла).
 */
export function runPayload({
  endpoint,
  until,
  stages,
  wishes,
  first,
}: {
  endpoint: string
  until: string | null
  stages: string[]
  wishes: Wishes
  first: boolean
}): RunPayload {
  const payload: RunPayload = { endpoint }
  const последняя = stages.length > 0 ? stages[stages.length - 1] : null
  if (until && until !== последняя && stages.includes(until)) payload.until = until
  if (first) payload.wishes = wishes
  return payload
}

/** Виды замечания к блоку (`kadai.rework.ROUTES`). Значения — ключи службы. */
export const REWORK_KINDS = ['кусок', 'схема', 'код', 'структура', 'условие'] as const
export type ReworkKind = (typeof REWORK_KINDS)[number]

/**
 * Тело задания `kadai_rework`.
 *
 * Ни `block`, ни `kind` не додумываются: сценарий отказывает на замечании без
 * адреса, и угаданный маршрут переписал бы не то (`kadai_rework.py`). «Убрать»
 * и «переставить» — это правка строения, поэтому у них вид `структура`, а само
 * действие сказано словами в замечании: своего вида «убери блок» у службы нет.
 */
export function reworkPayload({
  endpoint,
  block,
  kind,
  note,
}: {
  endpoint: string
  block: string
  kind: ReworkKind
  note: string
}): { endpoint: string; block: string; kind: string; note: string } {
  return { endpoint, block, kind, note: note.trim() }
}

export type BlockRecord = {
  key: string
  kind?: string | null
  label?: string | null
  source?: string | null
  value?: Record<string, unknown> | null
}

/**
 * Текст блока для карточки и для сравнения версий.
 *
 * Значение блока — запись `hokoku.wire`: у текста поле `text`/`markdown`, у
 * кода `code`, у схемы `xml`. Ключей три, а не один, потому что тип значения
 * решает движок отчётов, и своего разбора значений здесь не заводится — берём
 * первое строковое поле из известных.
 */
export function blockText(block: BlockRecord | undefined): string {
  const значение = block?.value
  if (!значение) return ''
  for (const поле of ['text', 'markdown', 'code', 'caption', 'xml']) {
    const это = значение[поле]
    if (typeof это === 'string' && это) return это
  }
  return ''
}

/** Весь список блоков одним текстом — левая сторона сравнения версий списка. */
export function blocksText(blocks: BlockRecord[] | undefined): string {
  return (blocks ?? []).map((b) => `${b.label || b.key}\n${blockText(b)}`.trim()).join('\n\n')
}
