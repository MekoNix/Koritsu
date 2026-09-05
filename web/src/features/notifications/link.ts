/**
 * link — куда ведёт уведомление и что по нему можно скачать.
 *
 * Служба присылает вид (`kind`) и данные (`data`), а не готовую ссылку, и это
 * правильно: адреса страниц знает сайт, а не служба (`packages/api/notifications/models.py`
 * — «`data` — JSON без единого объявленного поля»). Значит, соответствие
 * «вид задания → экран» живёт в одном месте, и это место здесь: его читают и
 * колокольчик, и виджет дашборда.
 *
 * Что лежит в `data` уведомления о задании (`notifications/service.py`):
 *
 *     job_id, job_kind, status, project_id, code, spent_units
 *     artifacts — {вид выхода: id артефакта}, только когда файл есть
 *
 * **Ссылки в никуда не бывает.** Проекта в данных нет — ссылки нет вовсе, и
 * запись в списке просто не кликается. Это прямое правило владельца: пункт,
 * ведущий в никуда, — ошибка, а не мелочь.
 */

/** Вид задания → экран, на котором виден его результат. */
const ЭКРАН: Record<string, (projectId: string) => string> = {
  // Разбор принесённого файла виден в описи материалов работы.
  parse: (id) => `/projects/${id}`,
  // Всё, что про текст отчёта, — на рабочем экране отчёта.
  fill_tag: (id) => `/reports/${id}`,
  fill_report: (id) => `/reports/${id}`,
  build: (id) => `/reports/${id}`,
  export: (id) => `/reports/${id}`,
  agent: (id) => `/reports/${id}`,
  // Задания — своя страница (ночь 2, область B).
  kadai_run: (id) => `/kadai/${id}`,
  kadai_rework: (id) => `/kadai/${id}`,
}

/** Строка из `data`, если она там строка и непустая. */
function строка(data: Record<string, unknown> | undefined, поле: string): string | null {
  const значение = data?.[поле]
  return typeof значение === 'string' && значение ? значение : null
}

/**
 * Куда вести по клику. `null` — вести некуда (например, `probe`: у него нет
 * ни проекта, ни экрана).
 */
export function notificationLink(data: Record<string, unknown> | undefined): string | null {
  const projectId = строка(data, 'project_id')
  if (!projectId) return null
  const вид = строка(data, 'job_kind') ?? ''
  const экран = ЭКРАН[вид]
  // Незнакомый вид ведёт на карточку работы: она есть у любого задания с
  // проектом, и это честнее, чем не вести никуда.
  return экран ? экран(projectId) : `/projects/${projectId}`
}

/** Порядок предпочтения: что скачивать, когда файлов несколько. */
const ВЫХОДЫ = ['pdf', 'file', 'docx', 'xml']

/**
 * Что скачать по уведомлению: адрес артефакта и его вид (`pdf`, `docx`, …).
 * Файла нет — `null`.
 *
 * Решение владельца: «экспорт — кнопка в проекте, задание, скачивание из
 * уведомления». Артефакты кладёт в `data.artifacts` служба (область C).
 */
export function notificationDownload(
  data: Record<string, unknown> | undefined,
): { url: string; kind: string } | null {
  const projectId = строка(data, 'project_id')
  const файлы = data?.artifacts
  if (!projectId || !файлы || typeof файлы !== 'object') return null
  const карта = файлы as Record<string, unknown>
  const виды = [...ВЫХОДЫ.filter((вид) => вид in карта), ...Object.keys(карта)]
  for (const вид of виды) {
    const id = карта[вид]
    if (typeof id === 'string' && id) {
      return {
        url: `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(id)}`,
        kind: вид,
      }
    }
  }
  return null
}
