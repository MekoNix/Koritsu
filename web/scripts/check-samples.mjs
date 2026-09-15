/**
 * Сверка примеров, которые лежат в дереве двумя копиями.
 *
 * Пример набора карточек нужен странице загрузки: пустую библиотеку он даёт
 * попробовать одним нажатием. Исходник живёт рядом с модулем разбора
 * (`packages/cards/samples/`), а образ сайта собирается из одного каталога
 * `web/` и каталога `packages/` не видит, поэтому рядом с областью лежит копия
 * (`src/features/cards/samples.ts` берёт ту, которая нашлась).
 *
 * Две копии одного файла расходятся молча: собранный сайт покажет пример
 * старее исходного, и заметить это будет негде — ни сборка, ни типы про такое
 * не знают. Поэтому расхождение ловит `pnpm lint`: та же команда, которой
 * область уже проверяют, а не отдельный шаг, который можно забыть.
 */
import { readFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const web = dirname(dirname(fileURLToPath(import.meta.url)))
const корень = dirname(web)

/** Пары «исходник → копия в дереве сайта». Сравниваются побайтово. */
const ПАРЫ = [
  {
    исходник: join(корень, 'packages/cards/samples/matan.json'),
    копия: join(web, 'src/features/cards/samples/matan.json'),
  },
]

/** Файл байтами или `null`, если его нет: отсутствие — такое же расхождение. */
function прочитать(путь) {
  try {
    return readFileSync(путь)
  } catch {
    console.error(`пример: нет файла ${relative(корень, путь)}`)
    return null
  }
}

let разошлось = false
for (const { исходник, копия } of ПАРЫ) {
  const а = прочитать(исходник)
  const б = прочитать(копия)
  if (а === null || б === null) {
    разошлось = true
    continue
  }
  if (!а.equals(б)) {
    console.error(
      `пример разошёлся: ${relative(корень, исходник)} и ${relative(корень, копия)} ` +
        'различаются. Копия повторяет исходник побайтово — обновите её:\n' +
        `  cp ${relative(корень, исходник)} ${relative(корень, копия)}`,
    )
    разошлось = true
  }
}

if (разошлось) process.exit(1)
