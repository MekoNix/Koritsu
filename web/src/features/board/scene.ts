/**
 * scene — как формула ложится в сцену Excalidraw и как сцена уезжает на том.
 *
 * Договор один на браузер и на службу: **формула — это группа элементов
 * `freedraw` с общим `groupIds[0]` вида `формула-<uuid>`, а `customData` лежит
 * у первого элемента группы в порядке массива `elements`**. «Первый» — первый
 * в массиве, а не первый нарисованный и не самый левый: порядок массива у
 * Excalidraw — это порядок отрисовки, он переживает сохранение и загрузку, и он
 * же виден службе. Другого общего понятия «первый» у браузера и службы нет.
 *
 * Поэтому разметка живёт здесь одной функцией: разъехавшийся «первый элемент»
 * означает, что служба увидит две формулы там, где человек написал одну.
 *
 * **Почему здесь нет ни одного импорта из `@excalidraw/excalidraw`.** Пакет
 * весит сотни килобайт и грузится ленивой загрузкой только на экране доски;
 * импорт отсюда затащил бы его в общий кусок и в модульные проверки, которым
 * редактор не нужен вовсе. Всё, что нужно, — пересчёт версии элемента (см.
 * `обновить`) и арифметика прямоугольников, и это дешевле повторить, чем тянуть
 * редактор ради двух строк.
 */

/**
 * Элемент сцены в том объёме, в каком его читает доска.
 *
 * Форма элемента принадлежит Excalidraw и меняется с его версиями; полная её
 * копия у нас разошлась бы с оригиналом молча. Здесь перечислено только то, что
 * область действительно трогает, а остальное едет на том нетронутым.
 */
export type SceneElement = {
  id: string
  type: string
  x: number
  y: number
  width?: number
  height?: number
  angle?: number
  isDeleted?: boolean
  groupIds?: string[]
  frameId?: string | null
  customData?: Record<string, unknown> | null
  /** У `freedraw` — локальные точки росчерка: первая всегда (0, 0). */
  points?: [number, number][]
  pressures?: number[]
  simulatePressure?: boolean
  version?: number
  versionNonce?: number
  updated?: number
  [k: string]: unknown
}

/** Прямоугольник в координатах сцены. */
export type Box = { x: number; y: number; width: number; height: number }

/** Откуда взялась строка LaTeX. Ровно три вида, как в договоре. */
export const SOURCES = {
  myscript: 'myscript',
  manual: 'manual',
  mathlive: 'mathlive',
} as const

export type FormulaSource = (typeof SOURCES)[keyof typeof SOURCES]

/**
 * Приставка имени группы формулы у групп, которые заводит доска.
 *
 * Узнают формулу **не по имени**, а по устройству: её группа — `groupIds[0]`
 * носителя, то есть самая внутренняя. Имя с приставкой нужно людям, читающим
 * сцену глазами, и только им: сцены, собранные не здесь (образцы службы,
 * перенесённые доски), зовут свои группы иначе и обязаны читаться так же.
 */
const ГРУППА = 'формула-'

/** То, что доска пишет в `customData` носителя формулы. */
export type FormulaData = {
  kind: 'formula'
  latex: string
  latexConfirmed: boolean
  latexSource: FormulaSource
  recognizedAt: string
}

/** Поля разметки формулы — те, что снимаются с не-первого элемента группы. */
const ПОЛЯ_ФОРМУЛЫ = ['kind', 'latex', 'latexConfirmed', 'latexSource', 'recognizedAt'] as const

/** Формула сцены: строка, её состояние и росчерки, из которых она собрана. */
export type SceneFormula = {
  /** Первый элемент группы — тот, у кого лежит `customData`. */
  carrier: SceneElement
  latex: string
  confirmed: boolean
  source: string
  elements: SceneElement[]
}

/** Уникальное имя группы. `randomUUID` есть везде, где есть безопасный контекст. */
function новоеИмяГруппы(): string {
  try {
    return `${ГРУППА}${crypto.randomUUID()}`
  } catch {
    return `${ГРУППА}${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  }
}

/**
 * Новый объект элемента с правками — то же, что делает `newElementWith`
 * редактора: поднимает `version`, `versionNonce` и `updated`.
 *
 * Именно новый объект, а не правка на месте: Excalidraw сравнивает элементы по
 * ссылке и версии, и изменение поля в существующем объекте до него не доходит.
 */
function обновить(элемент: SceneElement, правки: Partial<SceneElement>): SceneElement {
  return {
    ...элемент,
    ...правки,
    version: (элемент.version ?? 1) + 1,
    versionNonce: Math.floor(Math.random() * 2 ** 31),
    updated: Date.now(),
  }
}

/**
 * Пометить росчерки как одну формулу.
 *
 * Возвращается новый массив; старый не трогается. Имя группы берётся у уже
 * размеченных росчерков, если формулу правят повторно, — иначе каждая правка
 * плодила бы новую группу поверх старой, и служба считала бы формулы дважды.
 */
export function markFormula(
  elements: readonly SceneElement[],
  ids: Iterable<string>,
  latex: string,
  source: FormulaSource,
  confirmed = true,
  now: () => string = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
): SceneElement[] {
  const набор = ids instanceof Set ? (ids as Set<string>) : new Set(ids)
  const список = [...elements]
  if (набор.size === 0) return список

  // Имя группы берём у уже размеченных росчерков, если формулу правят повторно:
  // иначе каждая правка плодила бы новую группу поверх старой, и служба считала
  // бы формулы дважды.
  let имяГруппы: string | null = null
  for (const э of список) {
    if (!набор.has(э.id)) continue
    const своя = (э.groupIds ?? [])[0]
    if (своя) {
      имяГруппы = своя
      break
    }
  }
  имяГруппы ??= новоеИмяГруппы()

  const данные: FormulaData = {
    kind: 'formula',
    latex,
    latexConfirmed: Boolean(confirmed),
    latexSource: source,
    recognizedAt: now(),
  }

  let первый = true
  return список.map((э) => {
    if (!набор.has(э.id)) return э
    // Группа формулы — первая: так её и читает служба. Прежние группы человека
    // (объединение объектов) остаются за ней и не теряются.
    const группы = (э.groupIds ?? []).filter((г) => г !== имяГруппы)
    const правки: Partial<SceneElement> = { groupIds: [имяГруппы, ...группы] }
    if (первый) {
      первый = false
      правки.customData = { ...(э.customData ?? {}), ...данные }
    } else if ((э.customData as FormulaData | null)?.kind === 'formula') {
      // Хвост прежней разметки: у не-первого элемента группы формулы быть не
      // должно, иначе служба увидит две формулы там, где одна.
      const прочее = { ...(э.customData as Record<string, unknown>) }
      for (const поле of ПОЛЯ_ФОРМУЛЫ) delete прочее[поле]
      правки.customData = Object.keys(прочее).length ? прочее : null
    }
    return обновить(э, правки)
  })
}

/** Снять подтверждение с формулы: рукопись изменилась после того, как её приняли. */
export function unconfirmFormula(
  elements: readonly SceneElement[],
  carrierId: string,
): SceneElement[] {
  return elements.map((э) => {
    if (э.id !== carrierId) return э
    const данные = э.customData as FormulaData | null
    if (данные?.kind !== 'formula') return э
    return обновить(э, { customData: { ...данные, latexConfirmed: false } })
  })
}

/**
 * Все элементы формулы по любому её элементу.
 *
 * Группа формулы — `groupIds[0]`, самая внутренняя: так записано в договоре, и
 * так это читает служба. Росчерк без группы — формула из одного росчерка, и он
 * возвращается сам собой.
 */
export function formulaElements(elements: readonly SceneElement[], id: string): SceneElement[] {
  const якорь = elements.find((э) => э.id === id)
  const группа = (якорь?.groupIds ?? [])[0]
  if (!группа) return якорь ? [якорь] : []
  return elements.filter((э) => (э.groupIds ?? [])[0] === группа)
}

/** Носитель формулы — первый элемент группы, у которого лежит `customData`. */
export function formulaCarrier(elements: readonly SceneElement[], id: string): SceneElement | null {
  return formulaElements(elements, id)[0] ?? null
}

/**
 * Все формулы сцены в порядке массива элементов.
 *
 * Порядок чтения (сверху вниз) считает служба: у неё те же координаты, и
 * считать его дважды значит однажды разойтись. Здесь порядок нужен только
 * затем, чтобы чистовик рисовался в том же порядке, в каком строки стоят на
 * холсте, — отсюда `sortByReading`.
 */
export function sceneFormulas(elements: readonly SceneElement[]): SceneFormula[] {
  const найдено: SceneFormula[] = []
  for (const э of elements) {
    if (э.isDeleted) continue
    const данные = э.customData as FormulaData | null
    if (данные?.kind !== 'formula') continue
    найдено.push({
      carrier: э,
      latex: данные.latex ?? '',
      confirmed: Boolean(данные.latexConfirmed),
      source: данные.latexSource ?? '',
      elements: formulaElements(elements, э.id),
    })
  }
  return найдено
}

/**
 * Порядок чтения: сверху вниз, при равной высоте — слева направо.
 *
 * Это тот же порядок, в котором строки читает человек и собирает служба.
 * Сравнение по верхнему краю носителя, а не по центру: у строки с дробью центр
 * уезжает вниз, и «сверху вниз» переставляло бы её с соседкой.
 */
export function sortByReading(formulas: readonly SceneFormula[]): SceneFormula[] {
  return [...formulas].sort((а, б) => {
    const dy = а.carrier.y - б.carrier.y
    return Math.abs(dy) > 1 ? dy : а.carrier.x - б.carrier.x
  })
}

/**
 * Тело сцены для тома. `appState` — только фон и сетка.
 *
 * Прокрутка, зум и выделение в запись не входят намеренно: иначе каждое
 * движение холста было бы правкой сцены и порождало бы запись на том. Вид
 * холста живёт в браузере и на втором устройстве начинается заново.
 */
export function sceneToJSON(
  elements: readonly SceneElement[],
  appState?: { viewBackgroundColor?: string; gridSize?: number | null },
): {
  type: 'excalidraw'
  version: 2
  source: string
  elements: SceneElement[]
  appState: { viewBackgroundColor: string; gridSize: number | null }
} {
  return {
    type: 'excalidraw',
    version: 2,
    source: 'koritsu/board',
    elements: elements.filter((э) => !э.isDeleted),
    appState: {
      viewBackgroundColor: appState?.viewBackgroundColor ?? '#ffffff',
      gridSize: appState?.gridSize ?? null,
    },
  }
}

/** Габарит списка элементов в координатах сцены; `null` — считать нечего. */
export function bounds(elements: readonly SceneElement[]): Box | null {
  let слева = Infinity
  let сверху = Infinity
  let справа = -Infinity
  let снизу = -Infinity
  for (const э of elements) {
    if (!э || э.isDeleted) continue
    слева = Math.min(слева, э.x)
    сверху = Math.min(сверху, э.y)
    справа = Math.max(справа, э.x + (э.width ?? 0))
    снизу = Math.max(снизу, э.y + (э.height ?? 0))
  }
  if (!Number.isFinite(слева)) return null
  return { x: слева, y: сверху, width: справа - слева, height: снизу - сверху }
}

/** Высота строки текста, который кладётся на доску карточкой задачи. */
const СТРОКА = 25
const РАЗМЕР = 20

/**
 * Текстовый элемент сцены. Полями, а не фабрикой редактора: фабрика живёт в
 * ленивом куске, а положить задачу на доску надо из панели, которая уже открыта.
 * Всё, чего здесь нет, Excalidraw дочинит сам при разборе сцены.
 */
function текстовыйЭлемент(текст: string, x: number, y: number): SceneElement {
  const строки = текст.split('\n')
  const ширина = Math.max(...строки.map((с) => с.length)) * РАЗМЕР * 0.55
  return {
    id: `задача-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    type: 'text',
    x,
    y,
    width: Math.max(ширина, 120),
    height: строки.length * СТРОКА,
    angle: 0,
    text: текст,
    originalText: текст,
    fontSize: РАЗМЕР,
    fontFamily: 1,
    textAlign: 'left',
    verticalAlign: 'top',
    lineHeight: 1.25,
    containerId: null,
    // Цвет — тот же, что у пера по умолчанию: задача на доске должна выглядеть
    // как запись, а не как чужая наклейка.
    strokeColor: '#1e1e1e',
    backgroundColor: 'transparent',
    fillStyle: 'solid',
    strokeWidth: 1,
    strokeStyle: 'solid',
    roughness: 1,
    opacity: 100,
    groupIds: [],
    frameId: null,
    roundness: null,
    seed: Math.floor(Math.random() * 2 ** 31),
    version: 1,
    versionNonce: Math.floor(Math.random() * 2 ** 31),
    isDeleted: false,
    boundElements: null,
    updated: Date.now(),
    link: null,
    locked: false,
  }
}

/**
 * Положить задачу от репетитора на свободное место холста.
 *
 * Кладётся **ниже всего написанного**, с отступом: доска читается сверху вниз,
 * и задача, вставшая посреди решения, разорвала бы порядок шагов. Единственное,
 * что попадает на холст от агента, — эта задача, и кладёт её нажатие человека:
 * чужих объектов на доске не бывает, и вопрос «где моё» не возникает.
 */
export function placeTask(
  elements: readonly SceneElement[],
  task: string,
  latex: string,
): SceneElement[] {
  const рамка = bounds(elements.filter((э) => !э.isDeleted))
  const x = рамка ? рамка.x : 100
  const y = рамка ? рамка.y + рамка.height + 80 : 100
  const текст = текстовыйЭлемент(task.trim(), x, y)
  const добавленные = [текст]
  const формула = latex.trim()
  if (формула) {
    добавленные.push(текстовыйЭлемент(формула, x, y + текст.height! + 16))
  }
  return [...elements, ...добавленные]
}

/* ── короткий идентификатор строки ───────────────────────────────────────────
 *
 * Строку, уехавшую агенту, репетитор называет коротким именем: шесть
 * шестнадцатеричных знаков от sha256 идентификатора её якорного элемента. То же
 * имя стоит в выжимке, в файле распознанного и в замечании, которое приходит
 * обратно, — и по нему замечание разрешается в объект на доске. Считает его и
 * служба (`kokuban.scene`), и сайт: иначе замечание к «строке 3» не нашло бы на
 * холсте ничего.
 *
 * Почему sha256 написан здесь руками, а не взят у браузера. `crypto.subtle`
 * существует только в защищённом контексте, а сайт живёт по адресу без домена,
 * то есть по обычному http, — там его нет вовсе. Вторая причина не менее
 * весомая: он асинхронный, а имя строки нужно там же, где строится сама строка.
 */

/** Константы SHA-256: дробные части кубических корней первых 64 простых. */
const КОНСТАНТЫ = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

function вправо(значение: number, на: number): number {
  return ((значение >>> на) | (значение << (32 - на))) >>> 0
}

/** sha256 строки в шестнадцатеричном виде. Тот же, что у службы, байт в байт. */
export function sha256hex(текст: string): string {
  const байты = new TextEncoder().encode(текст)
  const длина = байты.length
  // Дополнение: единичный бит, нули и длина в битах восемью байтами с конца.
  const всего = (((длина + 8) >> 6) + 1) * 64
  const слово = new Uint8Array(всего)
  слово.set(байты)
  слово[длина] = 0x80
  const биты = длина * 8
  const хвост = new DataView(слово.buffer)
  хвост.setUint32(всего - 8, Math.floor(биты / 2 ** 32), false)
  хвост.setUint32(всего - 4, биты >>> 0, false)

  const состояние = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ])
  const очередь = new Uint32Array(64)
  for (let кусок = 0; кусок < всего; кусок += 64) {
    for (let и = 0; и < 16; и++) очередь[и] = хвост.getUint32(кусок + и * 4, false)
    for (let и = 16; и < 64; и++) {
      const п = очередь[и - 15] as number
      const с = очередь[и - 2] as number
      const н0 = вправо(п, 7) ^ вправо(п, 18) ^ (п >>> 3)
      const н1 = вправо(с, 17) ^ вправо(с, 19) ^ (с >>> 10)
      очередь[и] = ((очередь[и - 16] as number) + н0 + (очередь[и - 7] as number) + н1) >>> 0
    }
    let а = состояние[0] as number
    let б = состояние[1] as number
    let в = состояние[2] as number
    let г = состояние[3] as number
    let д = состояние[4] as number
    let е = состояние[5] as number
    let ж = состояние[6] as number
    let з = состояние[7] as number
    for (let и = 0; и < 64; и++) {
      const в1 = вправо(д, 6) ^ вправо(д, 11) ^ вправо(д, 25)
      const выбор = (д & е) ^ (~д & ж)
      const т1 = (з + в1 + выбор + (КОНСТАНТЫ[и] as number) + (очередь[и] as number)) >>> 0
      const в0 = вправо(а, 2) ^ вправо(а, 13) ^ вправо(а, 22)
      const большинство = (а & б) ^ (а & в) ^ (б & в)
      const т2 = (в0 + большинство) >>> 0
      з = ж
      ж = е
      е = д
      д = (г + т1) >>> 0
      г = в
      в = б
      б = а
      а = (т1 + т2) >>> 0
    }
    const шаг = [а, б, в, г, д, е, ж, з]
    for (let и = 0; и < 8; и++) состояние[и] = ((состояние[и] as number) + (шаг[и] as number)) >>> 0
  }
  let итог = ''
  for (const слово32 of состояние) итог += слово32.toString(16).padStart(8, '0')
  return итог
}

/** Сколько знаков в коротком имени по умолчанию. Столько же берёт служба. */
const КОРОТКО = 6

/**
 * Короткое имя строки по идентификатору её якорного элемента.
 *
 * При столкновении имя **удлиняется**, а не получает счётчик: счётчик зависел
 * бы от порядка обхода, и одна и та же доска называла бы строки по-разному от
 * раза к разу. `taken` — уже занятые имена этой доски; без него столкновения не
 * проверяются вовсе.
 */
export function shortId(elementId: string, taken?: Map<string, string>): string {
  const полное = sha256hex(String(elementId))
  for (let длина = КОРОТКО; длина <= полное.length; длина++) {
    const имя = полное.slice(0, длина)
    const занято = taken?.get(имя)
    if (занято === undefined || занято === elementId) {
      taken?.set(имя, elementId)
      return имя
    }
  }
  return полное
}
