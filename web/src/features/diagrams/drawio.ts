/**
 * drawio — разговор с draw.io: во встроенном кадре и в отдельном окне.
 *
 * Схема показывается не картинкой, а настоящим draw.io в
 * `<iframe>`. Общаются с ним не адресом, а сообщениями: страница и кадр стоят
 * на разных доменах, и всё, что между ними проходит, — это `postMessage` с
 * JSON внутри (протокол `?embed=1&proto=json`).
 *
 * Здесь собраны **чистые функции** этого разговора: как выглядит адрес кадра,
 * как выглядит сообщение «покажи вот этот XML» и как читается то, что кадр
 * присылает в ответ. Чистые — чтобы их можно было проверить тестом без
 * браузера и без сети: сам кадр в тестовой среде не поднимешь, а форму
 * сообщения сломать проще всего.
 *
 * Порядок разговора такой:
 *
 *     кадр → {"event":"init"}        редактор поднялся и готов
 *     мы  → {"action":"load", …}     вот XML, покажи
 *     кадр → {"event":"load"}        показал
 *     кадр → {"event":"autosave", "xml": …}   человек поправил схему руками
 *
 * `autosave` включается полем в самом `load`, а не параметром адреса: адрес
 * читается один раз при подъёме кадра, а грузим мы в него схему много раз.
 *
 * **Схема никогда не едет в адресе.** Прежде «открыть в draw.io» складывало XML
 * в сам адрес (`#R…`) — и на длинной схеме кнопка гасла: длину адреса режут и
 * браузер, и сервер draw.io, а обрезанный XML открывается пустым холстом, то
 * есть молча врёт. Поэтому и отдельное окно получает схему тем же сообщением,
 * что и кадр: адрес остаётся коротким и одинаковым, а длина схемы перестаёт
 * что-либо значить.
 */

/** Домен встроенного редактора. Сообщения с других доменов не читаются вовсе. */
export const EMBED_ORIGIN = 'https://embed.diagrams.net'

/** Домен обычного draw.io — туда уходит «Редактировать в draw.io». */
export const APP_ORIGIN = 'https://app.diagrams.net'

/** Домен просмотрщика — туда уходит «Просмотреть диаграмму». */
export const VIEWER_ORIGIN = 'https://viewer.diagrams.net'

/**
 * Пустая схема. Кадру нужно что-то показать до первого предпросмотра: без
 * `load` редактор висит на заставке, и человек читает это как «не загрузилось».
 */
export const EMPTY_XML =
  '<mxGraphModel dx="800" dy="600" grid="1" page="1">' +
  '<root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'

export type EmbedOptions = {
  /** Тёмный ли сейчас сайт: у редактора своя тема, и она обязана совпадать. */
  dark: boolean
  lang?: string
}

/**
 * Адрес кадра редактора.
 *
 * `embed=1&proto=json` — протокол сообщений; `spin=1` — своя заставка на время
 * подъёма; `libraries=0` — без панели фигур (схему рисует служба, а не
 * человек с нуля); `noSaveBtn`/`noExitBtn` — кнопок «Сохранить» и «Выйти» у
 * редактора нет: схема сохраняется в работу сама, и вторая кнопка с тем же
 * словом означала бы два разных сохранения на одном экране.
 */
export function embedUrl({ dark, lang = 'ru' }: EmbedOptions): string {
  const params = new URLSearchParams({
    embed: '1',
    proto: 'json',
    spin: '1',
    libraries: '0',
    noSaveBtn: '1',
    noExitBtn: '1',
    saveAndExit: '0',
    modified: 'unsavedChanges',
    dark: dark ? '1' : '0',
    lang,
  })
  return `${EMBED_ORIGIN}/?${params.toString()}`
}

/** Как часто проверяем, не закрыли ли отдельное окно. */
const ПРОВЕРКА_ОКНА_МС = 2000

/** Что делают в отдельном окне: правят схему или смотрят её. */
export type DrawioWindow = 'edit' | 'view'

/** Чьи сообщения слушать у окна такого вида. */
export function windowOrigin(kind: DrawioWindow): string {
  return kind === 'edit' ? APP_ORIGIN : VIEWER_ORIGIN
}

export type WindowOptions = EmbedOptions & { title?: string }

/**
 * Адрес отдельного окна draw.io: правки — на `app.diagrams.net`, просмотр — на
 * `viewer.diagrams.net`.
 *
 * Схемы в адресе нет: она уезжает сообщением после того, как окно скажет
 * `init` (см. шапку модуля). Поэтому адрес не зависит от длины схемы и одинаков
 * для схемы в три блока и в три тысячи.
 *
 * Правки в окне — полноценный draw.io: панель фигур включена (`libraries=1`), в
 * отличие от кадра на странице. Просмотр — `lightbox`: там нечего править, и
 * панели инструментов только мешали бы читать.
 */
export function drawioWindowUrl(
  kind: DrawioWindow,
  { dark, lang = 'ru', title = 'koritsu' }: WindowOptions,
): string {
  const общее = {
    embed: '1',
    proto: 'json',
    spin: '1',
    dark: dark ? '1' : '0',
    lang,
    title,
  }
  const params = new URLSearchParams(
    kind === 'edit'
      ? { ...общее, libraries: '1', noSaveBtn: '1', saveAndExit: '0' }
      : { ...общее, lightbox: '1', edit: '_blank' },
  )
  return `${windowOrigin(kind)}/?${params.toString()}`
}

/** Сообщение «покажи вот этот XML». `autosave` — чтобы правки возвращались нам. */
export function loadMessage(xml: string): string {
  return JSON.stringify({ action: 'load', autosave: 1, xml: xml || EMPTY_XML })
}

/** Сообщение «отдай текущий XML» — на случай, когда `autosave` ещё не пришёл. */
export function exportXmlMessage(): string {
  return JSON.stringify({ action: 'export', format: 'xml' })
}

/** Что присылает кадр. Полей у события больше, нам нужны эти три. */
export type EmbedEvent = {
  event: string
  xml?: string
  data?: string
}

/**
 * Прочитать то, что прислал кадр. Не наше — `null`.
 *
 * Проверка нужна не из брезгливости: `window.message` слышат все, кто умеет
 * писать в окно, — расширения браузера, соседние кадры, `postMessage` со
 * страницы. Всё, что не похоже на событие редактора, здесь и кончается.
 */
export function parseEmbedEvent(raw: unknown): EmbedEvent | null {
  let body: unknown = raw
  if (typeof raw === 'string') {
    if (!raw.startsWith('{')) return null
    try {
      body = JSON.parse(raw)
    } catch {
      return null
    }
  }
  if (!body || typeof body !== 'object') return null
  const record = body as Record<string, unknown>
  if (typeof record.event !== 'string' || !record.event) return null
  return {
    event: record.event,
    xml: typeof record.xml === 'string' ? record.xml : undefined,
    data: typeof record.data === 'string' ? record.data : undefined,
  }
}

/**
 * Открыть схему в отдельном окне draw.io. → открылось ли.
 *
 * Схема уезжает туда сообщением, когда окно отзовётся, а не адресом — иначе
 * длинная схема не открывалась бы вовсе (см. шапку модуля). Отсюда два
 * следствия, которых у обычной ссылки нет:
 *
 * * окно открывается **без** `noopener`: без ссылки на окно ему нечего послать.
 *   Плата известная и та же, что у встроенного кадра, — чужая страница знает
 *   про наше окно; отдаём мы ей ровно то, что и так открыто в кадре на этой же
 *   странице, а до нашей cookie и нашего DOM ей не достать по правилу
 *   происхождения;
 * * `window.open` обязан случиться **прямо в обработчике нажатия**, иначе
 *   браузер сочтёт окно всплывающим и закроет его. Поэтому здесь нет ни одного
 *   `await` до открытия.
 *
 * Правки из окна возвращаются тем же `autosave`, что и из кадра: человек,
 * подвинувший блок в большом редакторе, вправе ждать, что «скачать XML» отдаст
 * подвинутое. Слушатель снимается, когда окно закрыли: `message` слышит вся
 * страница, и забытый слушатель на каждое нажатие — это утечка, растущая
 * ровно от того, что человек часто пользуется кнопкой.
 */
export function openDrawioWindow(
  kind: DrawioWindow,
  xml: string,
  options: WindowOptions,
  onEdited?: (xml: string) => void,
): boolean {
  const origin = windowOrigin(kind)
  const окно = window.open(drawioWindowUrl(kind, options), '_blank')
  if (!окно) return false

  const сторож = window.setInterval(() => {
    if (окно.closed) отписаться()
  }, ПРОВЕРКА_ОКНА_МС)

  function отписаться() {
    window.clearInterval(сторож)
    window.removeEventListener('message', слушать)
  }

  function слушать(событие: MessageEvent) {
    if (событие.origin !== origin || событие.source !== окно) return
    const весть = parseEmbedEvent(событие.data)
    if (!весть) return
    if (весть.event === 'init') {
      окно?.postMessage(loadMessage(xml), origin)
      return
    }
    if (весть.event === 'exit') {
      отписаться()
      return
    }
    if ((весть.event === 'autosave' || весть.event === 'save') && весть.xml) {
      onEdited?.(весть.xml)
    }
  }

  window.addEventListener('message', слушать)
  return true
}
