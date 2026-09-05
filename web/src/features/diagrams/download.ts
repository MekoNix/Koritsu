/**
 * download — отдать человеку файл, который у нас уже в руках.
 *
 * Прямая ссылка на маршрут артефакта тут не годится: он требует cookie-сессии
 * и отдаёт `attachment`, а имя файла в нём — служебное. Поэтому файл берётся
 * запросом, а вниз уходит `Blob` под понятным именем.
 *
 * `URL.revokeObjectURL` — не вежливость: без него каждый «скачать XML» держит
 * копию схемы в памяти вкладки до перезагрузки.
 */

/** Сохранить содержимое под именем. Возвращать нечего: это действие, не запрос. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const ссылка = document.createElement('a')
  ссылка.href = url
  ссылка.download = filename
  document.body.appendChild(ссылка)
  ссылка.click()
  ссылка.remove()
  // Отпускаем не сразу: Safari успевает начать скачивание, только пока ссылка жива.
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export function saveText(text: string, filename: string, type = 'application/xml'): void {
  saveBlob(new Blob([text], { type: `${type};charset=utf-8` }), filename)
}

/**
 * Имя файла из имени проекта и вида схемы. Всё, что не буква и не цифра, —
 * в дефис: имя проекта пишет человек, а оно уезжает в файловую систему.
 */
export function safeFilename(base: string, ext: string): string {
  const чистое = base
    .trim()
    .replace(/[^\p{L}\p{N}_-]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return `${чистое || 'koritsu'}.${ext}`
}
