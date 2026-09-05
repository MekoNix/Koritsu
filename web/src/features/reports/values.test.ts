/**
 * Проверки формы значения тега по типу.
 *
 * Это зеркало `hokoku.wire`, и цена расхождения с оригиналом несимметрична: если
 * сайт строже службы, человек не может сохранить годное значение и не понимает
 * почему; если мягче — сохранение уезжает в службу и возвращается отказом уже
 * после нажатия, то есть проверка не сделала ничего. Поэтому проверяются обе
 * стороны: и что годное принимается, и что каждая беда названа своим кодом и
 * своим полем (по полю подписывается место в редакторе).
 */
import { describe, expect, it } from 'vitest'

import { blankValue, parseValue, validateValue, VALUE_TYPES } from './values'

describe('validateValue: годное', () => {
  it.each([
    ['text', { type: 'text', text: 'строка' }],
    ['markdown', { type: 'markdown', text: '# Заголовок' }],
    ['code', { type: 'code', text: 'print(1)', lang: 'py', line_numbers: null }],
    [
      'table',
      {
        type: 'table',
        rows: [
          ['a', 'b'],
          ['1', '2'],
        ],
        header: true,
        caption: 'Таблица 1',
        align: ['left', 'right'],
        col_widths_cm: [3, 4],
      },
    ],
    ['image', { type: 'image', artifact: '9f2ab0c1d2e3f405', caption: null, width_cm: 12 }],
    ['diagram', { type: 'diagram', artifact: '9f2ab0c1d2e3f405', page: 2 }],
    ['diagram по xml', { type: 'diagram', xml: '<mxfile/>', caption: false }],
    ['formula', { type: 'formula', latex: 'E = mc^2', numbered: true }],
    ['toc', { type: 'toc', levels: 3, title: null }],
    ['page_break', { type: 'page_break' }],
    ['blocks', { type: 'blocks', items: [{ type: 'text', text: 'кусок' }] }],
    ['версия схемы на верхнем уровне', { v: 1, type: 'text', text: 'из прошлой версии' }],
  ])('%s', (_имя, значение) => {
    expect(validateValue((значение as { type: string }).type, значение)).toBeNull()
  })
})

describe('validateValue: беды', () => {
  it.each([
    ['не объект', 'text', ['список'], 'notObject', 'value'],
    ['нет типа', 'text', { text: 'а' }, 'noType', 'type'],
    ['неизвестный тип', 'выдумка', { type: 'выдумка' }, 'unknownType', 'type'],
    ['тип не тот', 'text', { type: 'table', rows: [] }, 'typeMismatch', 'type'],
    ['лишнее поле', 'text', { type: 'text', text: 'а', captionn: 'б' }, 'unknownField', 'captionn'],
    ['нет обязательного', 'table', { type: 'table', header: true }, 'missing', 'rows'],
    ['строки не список', 'table', { type: 'table', rows: 'нет' }, 'notRows', 'rows'],
    ['ячейка не строка', 'table', { type: 'table', rows: [[1]] }, 'notRows', 'rows'],
    ['рваная таблица', 'table', { type: 'table', rows: [['a'], ['b', 'c']] }, 'raggedRows', 'rows'],
    [
      'выравниваний не по колонкам',
      'table',
      { type: 'table', rows: [['a', 'b']], align: ['left'] },
      'lengthMismatch',
      'align',
    ],
    ['латех не строка', 'formula', { type: 'formula', latex: 5 }, 'notString', 'latex'],
    ['нет латеха', 'formula', { type: 'formula', numbered: true }, 'missing', 'latex'],
    ['нет артефакта', 'image', { type: 'image', caption: 'Рисунок' }, 'missing', 'artifact'],
    [
      'путь вместо артефакта',
      'image',
      { type: 'image', artifact: '../../etc/passwd' },
      'notArtifact',
      'artifact',
    ],
    [
      'подпись true бессмысленна',
      'image',
      { type: 'image', artifact: 'ab12', caption: true },
      'notCaption',
      'caption',
    ],
    [
      'ширина не в сантиметрах',
      'image',
      { type: 'image', artifact: 'ab12', width_cm: 0 },
      'notNumber',
      'width_cm',
    ],
    [
      'выравнивание не из трёх',
      'image',
      { type: 'image', artifact: 'ab12', align: 'middle' },
      'notAlign',
      'align',
    ],
    ['у схемы ни того ни другого', 'diagram', { type: 'diagram' }, 'oneOfDiagram', 'artifact'],
    [
      'у схемы оба сразу',
      'diagram',
      { type: 'diagram', artifact: 'ab12', xml: '<mxfile/>' },
      'oneOfDiagram',
      'artifact',
    ],
    ['лист с нуля', 'diagram', { type: 'diagram', xml: '<m/>', page: 0 }, 'notPage', 'page'],
    ['глубина не в границах', 'toc', { type: 'toc', levels: 12 }, 'notLevels', 'levels'],
    ['версия из будущего', 'text', { v: 9, type: 'text', text: 'а' }, 'badVersion', 'v'],
    [
      'blocks внутри blocks',
      'blocks',
      { type: 'blocks', items: [{ type: 'blocks', items: [] }] },
      'nestedBlocks',
      'items[0].type',
    ],
    [
      'беда внутри blocks названа по месту',
      'blocks',
      { type: 'blocks', items: [{ type: 'formula' }] },
      'missing',
      'items[0].latex',
    ],
    [
      'версия на вложенном куске',
      'blocks',
      { type: 'blocks', items: [{ v: 2, type: 'text', text: 'а' }] },
      'badVersion',
      'items[0].v',
    ],
  ])('%s', (_имя, тип, значение, code, field) => {
    expect(validateValue(тип as string, значение)).toEqual({ code, field })
  })
})

describe('parseValue', () => {
  it('не JSON — это своя беда, а не «форма не та»', () => {
    expect(parseValue('table', '{ rows: [] }')).toEqual({
      value: null,
      problem: { code: 'badJson', field: '' },
    })
  })

  it('тип берётся у самого значения, а не у тега', () => {
    // Служба объявленный тип тега не сверяет (тип бывает угадан по метке), и
    // редактор не должен спорить с тем, что служба примет.
    const текст = JSON.stringify({ type: 'markdown', text: 'пока словами' })
    expect(parseValue('diagram', текст).problem).toBeNull()
  })

  it('годное отдаётся разобранным — им и пишут значение', () => {
    const разбор = parseValue('formula', '{"type":"formula","latex":"x^2"}')
    expect(разбор.problem).toBeNull()
    expect(разбор.value).toEqual({ type: 'formula', latex: 'x^2' })
  })
})

describe('blankValue', () => {
  it('заготовка есть у каждого типа и она этого типа', () => {
    for (const тип of VALUE_TYPES) {
      expect(blankValue(тип).type).toBe(тип)
    }
  })

  it('заготовка таблицы годится к отправке как есть', () => {
    expect(validateValue('table', blankValue('table'))).toBeNull()
  })

  it('заготовка картинки к отправке НЕ годится: артефакт называет человек', () => {
    // Это не недосмотр: «сохранилось само» с пустой ссылкой было бы хуже отказа
    // — рисунок в отчёте оказался бы дырой, и заметил бы это читатель.
    expect(validateValue('image', blankValue('image'))).toEqual({
      code: 'notArtifact',
      field: 'artifact',
    })
  })

  it('незнакомый тип не роняет заготовку', () => {
    expect(blankValue('выдумка')).toEqual({ type: 'markdown', text: '' })
  })
})
