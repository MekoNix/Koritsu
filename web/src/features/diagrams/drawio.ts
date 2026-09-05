/**
 * drawio — разговор с встроенным редактором `embed.diagrams.net`.
 *
 * Решение владельца: схема показывается не картинкой, а настоящим draw.io в
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
 */

/** Домен встроенного редактора. Сообщения с других доменов не читаются вовсе. */
export const EMBED_ORIGIN = 'https://embed.diagrams.net'

/** Домен обычного draw.io — туда уходит кнопка «Открыть в draw.io». */
export const APP_ORIGIN = 'https://app.diagrams.net'

/**
 * Пустая схема. Кадру нужно что-то показать до первого предпросмотра: без
 * `load` редактор висит на заставке, и человек читает это как «не загрузилось».
 */
export const EMPTY_XML =
  '<mxGraphModel dx="800" dy="600" grid="1" page="1">' +
  '<root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'

/**
 * Сколько знаков XML ещё влезает в адрес `#R…`. Ограничение не наше: длину
 * адреса режут и браузер, и сервер draw.io, а обрезанный XML открывается
 * пустым холстом — то есть молча врёт. Поэтому длинную схему в ссылку не
 * кладём вовсе и говорим об этом словами.
 */
export const OPEN_URL_MAX = 100_000

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
 * редактора нет: сохранение у нас своё, в проект, и вторая кнопка с тем же
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
 * Ссылка «Открыть в draw.io»: схема едет в самом адресе (`#R` — сырой XML).
 *
 * Слишком длинная схема — `null`, а не обрезанная ссылка: см. `OPEN_URL_MAX`.
 */
export function drawioOpenUrl(xml: string, title = 'koritsu'): string | null {
  if (!xml) return null
  const encoded = encodeURIComponent(xml)
  if (encoded.length > OPEN_URL_MAX) return null
  return `${APP_ORIGIN}/?title=${encodeURIComponent(title)}#R${encoded}`
}
