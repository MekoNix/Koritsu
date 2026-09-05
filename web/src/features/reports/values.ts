/**
 * values — форма значения тега по его типу: проверка и заготовка.
 *
 * Нетекстовые теги (таблица, картинка, схема, формула) человек правит текстовым
 * JSON. Значит на сайте появляется место, где можно
 * написать что угодно, и вопрос «годится ли это» перестаёт быть теоретическим.
 *
 * **Правило одно и то же с обеих сторон.** Служба разбирает значение
 * `hokoku.wire.value_from_json` — тем же, которым его прочтёт сборщик отчёта, —
 * и отвечает `400 invalid_value` с `where` на поле
 * (`packages/api/projects/routes.проверить_форму`). Здесь стоит его зеркало:
 * те же обязательные поля, тот же перечень допустимых, те же три состояния
 * подписи. Зеркало нужно не вместо отказа службы, а до него: человек, набирая
 * JSON, обязан видеть беду под курсором, а не после нажатия «сохранить».
 * Последнее слово при этом всё равно за службой — её отказ показывается тоже.
 *
 * **Текстов здесь нет ни одного.** Проверка возвращает `{code, field}`, а
 * русскую фразу собирает компонент по ключу перевода: правило брифа про голые
 * строки в коде действует и на сообщения об ошибке.
 *
 * Что зеркалится, а что нет. Поля и их виды — да, целиком (`_TYPES` в
 * `hokoku/wire.py`). Существование артефакта — нет: проверить его можно только
 * походом на том, и это дело службы. Совпадение с объявленным типом тега —
 * тоже нет, и по той же причине, что у службы: тип в манифесте часто угадан по
 * метке, и защищать догадку от правды незачем.
 */

/** Типы значений — те же слова, что у `hokoku.wire.VALUE_TYPES`. */
export const VALUE_TYPES = [
  'text',
  'markdown',
  'code',
  'image',
  'diagram',
  'table',
  'formula',
  'toc',
  'page_break',
  'blocks',
] as const

export type ValueType = (typeof VALUE_TYPES)[number]

/** Версия схемы значения (`hokoku.wire.WIRE_VERSION`): читатель знает до неё. */
export const WIRE_VERSION = 2

/** Выравнивание — те же три слова, что у службы. */
const ВЫРАВНИВАНИЕ = ['left', 'center', 'right']

/** Идентификатор артефакта: букв, цифр и `_.-`, до 64 знаков. Путей нет. */
const АРТЕФАКТ_RE = /^[A-Za-z0-9_.-]{1,64}$/

/** Что не так со значением. Текст к коду — в переводах `reports.json.error.*`. */
export type ValueProblemCode =
  /** Текст в редакторе — вовсе не JSON. Служба такого не увидит: до неё не доедет. */
  | 'badJson'
  | 'notObject'
  | 'noType'
  | 'unknownType'
  | 'typeMismatch'
  | 'unknownField'
  | 'missing'
  | 'notString'
  | 'notFlag'
  | 'notNumber'
  | 'notCaption'
  | 'notAlign'
  | 'notArtifact'
  | 'notRows'
  | 'raggedRows'
  | 'notList'
  | 'notLevels'
  | 'notPage'
  | 'lengthMismatch'
  | 'oneOfDiagram'
  | 'nestedBlocks'
  | 'badVersion'

/** Беда значения: код и место — `rows`, `items[0].latex`, `type`. */
export type ValueProblem = { code: ValueProblemCode; field: string }

type Вид = (значение: unknown, поле: string) => ValueProblem | null

type Поле = { вид: Вид; обязательное?: boolean }

const беда = (code: ValueProblemCode, field: string): ValueProblem => ({ code, field })

const строка: Вид = (v, поле) => (typeof v === 'string' ? null : беда('notString', поле))

const строка_или_ничего: Вид = (v, поле) =>
  v === null || typeof v === 'string' ? null : беда('notString', поле)

const флаг: Вид = (v, поле) => (typeof v === 'boolean' ? null : беда('notFlag', поле))

const флаг_или_ничего: Вид = (v, поле) =>
  v === null || typeof v === 'boolean' ? null : беда('notFlag', поле)

/** Размер в сантиметрах: число больше нуля или `null` — «взять из стиля». */
const размер: Вид = (v, поле) =>
  v === null || (typeof v === 'number' && Number.isFinite(v) && v > 0)
    ? null
    : беда('notNumber', поле)

/**
 * Подпись трёхзначна, и JSON выражает это сам: строка — подпись с текстом,
 * `null` — «Рисунок N» без текста, `false` — без подписи и без номера.
 * `true` бессмысленно, поэтому отвергается (как и у службы).
 */
const подпись: Вид = (v, поле) =>
  v === null || v === false || typeof v === 'string' ? null : беда('notCaption', поле)

const выравнивание: Вид = (v, поле) =>
  typeof v === 'string' && ВЫРАВНИВАНИЕ.includes(v) ? null : беда('notAlign', поле)

const артефакт: Вид = (v, поле) =>
  typeof v === 'string' && АРТЕФАКТ_RE.test(v) && !v.includes('..')
    ? null
    : беда('notArtifact', поле)

const уровни: Вид = (v, поле) =>
  Number.isInteger(v) && (v as number) >= 1 && (v as number) <= 9 ? null : беда('notLevels', поле)

const лист: Вид = (v, поле) =>
  v === null || (Number.isInteger(v) && (v as number) >= 1) ? null : беда('notPage', поле)

const список: Вид = (v, поле) => (Array.isArray(v) ? null : беда('notList', поле))

/** Список чисел или `null`: ширины колонок. */
const ширины: Вид = (v, поле) => {
  if (v === null) return null
  if (!Array.isArray(v)) return беда('notList', поле)
  for (const х of v) {
    const плохо = размер(х, поле)
    if (плохо) return плохо
  }
  return null
}

/** Список выравниваний или `null`: по колонке на каждую. */
const выравнивания: Вид = (v, поле) => {
  if (v === null) return null
  if (!Array.isArray(v)) return беда('notList', поле)
  for (const х of v) {
    const плохо = выравнивание(х, поле)
    if (плохо) return плохо
  }
  return null
}

/**
 * Строки таблицы: список списков строк, все одной длины.
 *
 * Рваную таблицу служба не чинит намеренно: тихая дыра в отчёте неотличима от
 * задуманной пустой ячейки.
 */
const строки: Вид = (v, поле) => {
  if (!Array.isArray(v)) return беда('notRows', поле)
  let ширина: number | null = null
  for (const строка_таблицы of v) {
    if (!Array.isArray(строка_таблицы)) return беда('notRows', поле)
    for (const ячейка of строка_таблицы) {
      if (typeof ячейка !== 'string') return беда('notRows', поле)
    }
    if (ширина === null) ширина = строка_таблицы.length
    else if (строка_таблицы.length !== ширина) return беда('raggedRows', поле)
  }
  return null
}

/** Поля каждого типа — один в один с `_TYPES` в `hokoku/wire.py`. */
const ТИПЫ: Record<ValueType, Record<string, Поле>> = {
  text: { text: { вид: строка, обязательное: true } },
  markdown: { text: { вид: строка, обязательное: true } },
  code: {
    text: { вид: строка, обязательное: true },
    lang: { вид: строка },
    line_numbers: { вид: флаг_или_ничего },
    highlight: { вид: флаг_или_ничего },
    // у листинга нет третьего состояния подписи, поэтому здесь не `подпись`
    caption: { вид: строка_или_ничего },
    ref: { вид: строка_или_ничего },
  },
  image: {
    artifact: { вид: артефакт, обязательное: true },
    caption: { вид: подпись },
    width_cm: { вид: размер },
    align: { вид: выравнивание },
    ref: { вид: строка_или_ничего },
  },
  diagram: {
    artifact: { вид: артефакт },
    xml: { вид: строка },
    caption: { вид: подпись },
    width_cm: { вид: размер },
    align: { вид: выравнивание },
    ref: { вид: строка_или_ничего },
    page: { вид: лист },
  },
  table: {
    rows: { вид: строки, обязательное: true },
    header: { вид: флаг },
    caption: { вид: подпись },
    col_widths_cm: { вид: ширины },
    align: { вид: выравнивания },
    ref: { вид: строка_или_ничего },
  },
  formula: {
    latex: { вид: строка, обязательное: true },
    numbered: { вид: флаг },
    ref: { вид: строка_или_ничего },
  },
  toc: { levels: { вид: уровни }, title: { вид: строка_или_ничего } },
  page_break: {},
  blocks: { items: { вид: список, обязательное: true } },
}

function известен(type: unknown): type is ValueType {
  return typeof type === 'string' && (VALUE_TYPES as readonly string[]).includes(type)
}

/**
 * Годится ли `value` как значение тега типа `type`. `null` — годится.
 *
 * Возвращается ПЕРВАЯ беда, а не список: в редакторе JSON вторая почти всегда
 * следствие первой (пропущенная запятая), и показывать их пачкой значило бы
 * посылать человека чинить то, чего нет.
 */
export function validateValue(type: string, value: unknown): ValueProblem | null {
  if (!известен(type)) return беда('unknownType', 'type')
  return проверить(type, value, '', false)
}

function проверить(
  type: ValueType,
  value: unknown,
  путь: string,
  вложено: boolean,
): ValueProblem | null {
  const где = (поле: string) => (путь ? `${путь}.${поле}` : поле)
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return беда('notObject', путь || 'value')
  }
  const тело = value as Record<string, unknown>

  if (тело.type === undefined) return беда('noType', где('type'))
  if (!известен(тело.type)) return беда('unknownType', где('type'))
  if (тело.type !== type) return беда('typeMismatch', где('type'))
  if (вложено && тело.type === 'blocks') return беда('nestedBlocks', где('type'))

  if ('v' in тело) {
    if (вложено) return беда('badVersion', где('v'))
    const v = тело.v
    if (!Number.isInteger(v) || (v as number) < 1 || (v as number) > WIRE_VERSION) {
      return беда('badVersion', где('v'))
    }
  }

  const поля = ТИПЫ[type]
  for (const [имя, значение] of Object.entries(тело)) {
    if (имя === 'type' || имя === 'v') continue
    const поле = поля[имя]
    if (!поле) return беда('unknownField', где(имя))
    const плохо = поле.вид(значение, где(имя))
    if (плохо) return плохо
  }
  for (const [имя, поле] of Object.entries(поля)) {
    if (поле.обязательное && !(имя in тело)) return беда('missing', где(имя))
  }

  return особое(type, тело, путь, где)
}

/** Проверки, которых не выразить полем поодиночке: связи между полями. */
function особое(
  type: ValueType,
  тело: Record<string, unknown>,
  путь: string,
  где: (поле: string) => string,
): ValueProblem | null {
  if (type === 'diagram') {
    // Ровно одно из двух: схема приходит либо артефактом, либо строкой XML.
    const есть_артефакт = 'artifact' in тело
    const есть_xml = 'xml' in тело
    if (есть_артефакт === есть_xml) return беда('oneOfDiagram', где('artifact'))
  }
  if (type === 'table') {
    const rows = тело.rows as string[][]
    const колонок = rows.length > 0 ? (rows[0]?.length ?? 0) : 0
    for (const имя of ['align', 'col_widths_cm'] as const) {
      const список_полей = тело[имя]
      if (Array.isArray(список_полей) && rows.length > 0 && список_полей.length !== колонок) {
        return беда('lengthMismatch', где(имя))
      }
    }
  }
  if (type === 'blocks') {
    const items = тело.items as unknown[]
    for (let i = 0; i < items.length; i += 1) {
      const кусок = items[i]
      const внутри = `${путь ? `${путь}.` : ''}items[${i}]`
      if (кусок === null || typeof кусок !== 'object' || Array.isArray(кусок)) {
        return беда('notObject', внутри)
      }
      const свой = (кусок as Record<string, unknown>).type
      if (свой === undefined) return беда('noType', `${внутри}.type`)
      if (!известен(свой)) return беда('unknownType', `${внутри}.type`)
      const плохо = проверить(свой, кусок, внутри, true)
      if (плохо) return плохо
    }
  }
  return null
}

/**
 * Заготовка значения по типу — то, что показывается в пустом редакторе.
 *
 * Пустой `{}` человеку ничего не говорит: он не знает ни имён полей, ни того,
 * что у таблицы строки списками списков. Заготовка отвечает на это раньше, чем
 * вопрос задан, и намеренно не годится к сохранению там, где без человека
 * значения нет (`artifact` пустой): «сохранилось само» здесь было бы хуже
 * отказа.
 */
export function blankValue(type: string): Record<string, unknown> {
  switch (type) {
    case 'table':
      return {
        type,
        rows: [
          ['', ''],
          ['', ''],
        ],
        header: true,
        caption: null,
      }
    case 'image':
      return { type, artifact: '', caption: null }
    case 'diagram':
      return { type, artifact: '', caption: null }
    case 'formula':
      return { type, latex: '', numbered: true }
    case 'toc':
      return { type, levels: 2, title: null }
    case 'page_break':
      return { type }
    case 'blocks':
      return { type, items: [] }
    case 'code':
      return { type, text: '', lang: '' }
    default:
      return { type: известен(type) ? type : 'markdown', text: '' }
  }
}

/** Разобранное значение или беда. `value` есть тогда и только тогда, когда беды нет. */
export type ParsedValue =
  { value: Record<string, unknown>; problem: null } | { value: null; problem: ValueProblem }

/**
 * Текст редактора → значение, годное к отправке. Разбор и проверка вместе.
 *
 * Тип берётся из самого значения, а объявленный тип тега — только запасной:
 * человек вправе поставить в тег картинку там, где служба угадала схему (см.
 * шапку), и редактор не должен спорить с тем, что служба примет.
 */
export function parseValue(type: string, text: string): ParsedValue {
  let разобрано: unknown
  try {
    разобрано = JSON.parse(text)
  } catch {
    return { value: null, problem: беда('badJson', '') }
  }
  const свой = (разобрано as { type?: unknown } | null)?.type
  const плохо = validateValue(typeof свой === 'string' ? свой : type, разобрано)
  if (плохо) return { value: null, problem: плохо }
  return { value: разобрано as Record<string, unknown>, problem: null }
}

/** Значение → текст редактора. Отступ в два пробела, как в остальном JSON. */
export function valueToJson(value: unknown, type: string): string {
  const тело =
    value && typeof value === 'object' && !Array.isArray(value) ? value : blankValue(type)
  return JSON.stringify(тело, null, 2)
}
