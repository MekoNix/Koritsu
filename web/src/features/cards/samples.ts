/**
 * samples — пример набора для пустой библиотеки.
 *
 * Текст примера — файл `packages/cards/samples/matan.json` (темы и формулы). Сайт не
 * создаёт набор из него сам: текст уходит в превью так же, как вставленный человеком,
 * и дальше идёт обычная загрузка — видно и формат файла, и проверку.
 *
 * Файл берётся сборкой как текст (`?raw`), а не как модуль JSON: в превью уходит файл в
 * том виде, в каком его увидит человек. Ищется в двух местах: копия рядом с модулем
 * (`./samples/matan.json`) и исходник в `packages/`. Сборка образа сайта видит только
 * каталог `web/`, поэтому для неё нужна копия; не нашлось ни одного — кнопки примера
 * нет, а не кнопка, которая ничего не делает.
 */

const найденные: Record<string, () => Promise<string>> = {
  ...import.meta.glob<string>('./samples/matan.json', { query: '?raw', import: 'default' }),
  ...import.meta.glob<string>('../../../../packages/cards/samples/matan.json', { query: '?raw', import: 'default' }),
}

const загрузчик = Object.values(найденные)[0]

export const hasSample: boolean = !!загрузчик

/** Текст примера и имя файла для превью. */
export async function loadSample(): Promise<{ text: string; filename: string }> {
  if (!загрузчик) throw new Error('cards sample is not bundled')
  return { text: await загрузчик(), filename: 'matan.json' }
}
