import { describe, expect, it } from 'vitest'

import {
  DONE,
  RUNNING,
  SKIPPED,
  WAITING,
  blockText,
  blocksText,
  currentStage,
  mergeStages,
  reached,
  reworkPayload,
  runPayload,
} from './stages'

const ИМЕНА = ['приём', 'разбор задания', 'шаблон', 'решение', 'тексты', 'сборка', 'архив']

describe('mergeStages', () => {
  it('накладывает события потока на снимок, а не заменяет его', () => {
    // Снимок устаревает, пока идёт прогон: перечитывать его на каждое событие
    // значило бы гнать запрос раз в секунду ради того, что уже приехало.
    const снимок = [
      { name: 'приём', state: DONE, note: '1 материал' },
      { name: 'разбор задания', state: WAITING },
      { name: 'шаблон', state: WAITING },
    ]
    const итог = mergeStages(ИМЕНА, снимок, [
      { name: 'разбор задания', state: DONE },
      { name: 'шаблон', state: RUNNING },
    ])
    expect(итог.map((s) => s.state)).toEqual([
      DONE,
      DONE,
      RUNNING,
      WAITING,
      WAITING,
      WAITING,
      WAITING,
    ])
    // Заметка стадии живёт в снимке, событие её не затирает.
    expect(итог[0]?.note).toBe('1 материал')
  })

  it('без списка имён берёт порядок из снимка', () => {
    const итог = mergeStages([], [{ name: 'приём', state: DONE }], [])
    expect(итог.map((s) => s.name)).toEqual(['приём'])
  })

  it('стадии, которой нет в снимке, — «ждёт», а не «пропущена»', () => {
    // Разница видна человеку: «пропущена» значит, что стадии не будет вовсе.
    const итог = mergeStages(ИМЕНА, [], [])
    expect(итог.every((s) => s.state === WAITING)).toBe(true)
  })
})

describe('currentStage и reached', () => {
  it('идущая стадия важнее ждущей', () => {
    const стадии = mergeStages(ИМЕНА, [{ name: 'шаблон', state: RUNNING }], [])
    expect(currentStage(стадии)).toBe('шаблон')
  })

  it('пропущенная стадия считается пройденной', () => {
    const стадии = mergeStages(
      ИМЕНА,
      [
        { name: 'приём', state: DONE },
        { name: 'решение', state: SKIPPED },
      ],
      [],
    )
    expect(reached(стадии, 'решение')).toBe(true)
    expect(reached(стадии, 'тексты')).toBe(false)
  })
})

describe('runPayload', () => {
  it('пожелания только в первый прогон', () => {
    // Служба заводит работу один раз и пожелания второго прогона выбрасывает
    // молча (`orchestrator.kadai.work`).
    const пожелания = { text: 'короче', show_task: true, show_structure: false }
    const первый = runPayload({
      endpoint: 'deepseek',
      until: null,
      stages: ИМЕНА,
      wishes: пожелания,
      first: true,
    })
    const второй = runPayload({
      endpoint: 'deepseek',
      until: null,
      stages: ИМЕНА,
      wishes: пожелания,
      first: false,
    })
    expect(первый.wishes).toEqual(пожелания)
    expect(второй.wishes).toBeUndefined()
  })

  it('«до конца» не кладёт until вовсе', () => {
    const до_конца = runPayload({
      endpoint: 'deepseek',
      until: 'архив',
      stages: ИМЕНА,
      wishes: { text: '', show_task: false, show_structure: false },
      first: false,
    })
    expect(до_конца.until).toBeUndefined()
  })

  it('до промежуточной стадии — кладёт её имя', () => {
    const до_сборки = runPayload({
      endpoint: 'deepseek',
      until: 'сборка',
      stages: ИМЕНА,
      wishes: { text: '', show_task: false, show_structure: false },
      first: false,
    })
    expect(до_сборки).toEqual({ endpoint: 'deepseek', until: 'сборка' })
  })

  it('стадии, которой служба не знает, в payload не бывает', () => {
    // Иначе служба отвечает `unknown_stage`, а человек уже заплатил за
    // постановку задания.
    const итог = runPayload({
      endpoint: 'deepseek',
      until: 'выдуманная',
      stages: ИМЕНА,
      wishes: { text: '', show_task: false, show_structure: false },
      first: false,
    })
    expect(итог.until).toBeUndefined()
  })
})

describe('reworkPayload', () => {
  it('адрес блока и вид замечания кладутся как есть', () => {
    expect(
      reworkPayload({
        endpoint: 'deepseek',
        block: 'b-03',
        kind: 'кусок',
        note: '  введение не про то  ',
      }),
    ).toEqual({ endpoint: 'deepseek', block: 'b-03', kind: 'кусок', note: 'введение не про то' })
  })
})

describe('blockText', () => {
  it('берёт первое известное строковое поле значения', () => {
    expect(blockText({ key: 'b-01', value: { type: 'markdown', text: 'абзац' } })).toBe('абзац')
    expect(blockText({ key: 'b-02', value: { type: 'code', code: 'print(1)' } })).toBe('print(1)')
    expect(blockText({ key: 'b-03', value: null })).toBe('')
  })

  it('весь список одним текстом — для сравнения версий', () => {
    expect(
      blocksText([
        { key: 'b-01', label: 'Введение', value: { text: 'раз' } },
        { key: 'b-02', label: '', value: { text: 'два' } },
      ]),
    ).toBe('Введение\nраз\n\nb-02\nдва')
  })
})
