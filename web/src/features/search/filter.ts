/**
 * filter — что палитра показывает по набранному.
 *
 * Отбор считает сайт, а не служба: у `GET /api/projects` нет параметра поиска,
 * а списки, по которым ищем, у сайта уже загружены (проекты всех пространств и
 * материалы открытой работы). Заводить ради подстроки маршрут в службе значило
 * бы завести и второе описание того, что такое совпадение.
 *
 * Правила отбора, и все три из того, как люди на самом деле ищут:
 *
 * 1. **регистр и «ё» не считаются** — «Ёлка», «елка» и «ЕЛКА» одно и то же;
 * 2. **совпадение по подстроке, а не по началу** — работу зовут «Лабораторная
 *    4 — сортировки», и набирают в поиске «сорти», а не «лабо»;
 * 3. **слова ищутся все и в любом порядке** — «4 лаб» находит ту же работу.
 *
 * Порядок выдачи: сперва то, где совпадение ближе к началу имени, потом
 * короткие имена (короткое имя, содержащее набранное, — обычно и есть нужное).
 * Проекты идут выше материалов: работу ищут чаще, чем файл внутри неё.
 */

export type ProjectHit = {
  kind: 'project'
  id: string
  name: string
  /** Имя пространства — в списке из нескольких пространств без него не понять. */
  workspace: string
  to: string
}

export type MaterialHit = {
  kind: 'material'
  id: string
  name: string
  /** Имя работы, в которой лежит файл. */
  project: string
  to: string
}

export type Hit = ProjectHit | MaterialHit

/** Привести к виду, в котором сравниваются строки. */
export function normalize(text: string): string {
  return text.toLowerCase().replace(/ё/g, 'е').trim()
}

/**
 * Насколько строка подходит под запрос. `null` — не подходит вовсе, иначе
 * число: чем меньше, тем выше в списке.
 */
export function score(name: string, query: string): number | null {
  const строка = normalize(name)
  const слова = normalize(query).split(/\s+/).filter(Boolean)
  if (слова.length === 0) return 0
  let лучшее = Number.MAX_SAFE_INTEGER
  for (const слово of слова) {
    const где = строка.indexOf(слово)
    if (где < 0) return null
    лучшее = Math.min(лучшее, где)
  }
  // Позиция самого раннего совпадения плюс сотая доля длины имени: при равной
  // позиции короткое имя оказывается выше длинного.
  return лучшее + строка.length / 100
}

/** Отобрать и отсортировать. Пустой запрос — пустая выдача, а не всё подряд. */
export function filterHits(hits: Hit[], query: string, limit = 20): Hit[] {
  if (!normalize(query)) return []
  const ВЕС = { project: 0, material: 1 }
  const отобранные: { hit: Hit; score: number }[] = []
  for (const hit of hits) {
    const очки = score(hit.name, query)
    if (очки === null) continue
    отобранные.push({ hit, score: очки + ВЕС[hit.kind] * 1000 })
  }
  отобранные.sort((a, b) => a.score - b.score)
  return отобранные.slice(0, limit).map((строка) => строка.hit)
}

/**
 * Идентификатор работы, открытой сейчас, — из адреса страницы.
 *
 * Палитра живёт в шапке, то есть выше маршрутов области, и `useParams` ей
 * ничего не даст: у оболочки своих параметров нет. Поэтому адрес разбирается
 * строкой — и заодно это единственное место, где записано, что работа
 * открыта на `/projects/:id`, `/reports/:id`, `/kadai/:id` и схемах.
 */
const С_ПРОЕКТОМ = /^\/(?:projects|reports|kadai|flowcharts|uml|diagrams)\/([0-9a-fA-F-]{36})/

export function currentProjectId(pathname: string): string | null {
  const совпало = С_ПРОЕКТОМ.exec(pathname)
  return совпало?.[1] ?? null
}
