/**
 * Шрифты доски — к себе, чтобы браузер не ходил на чужие CDN.
 *
 * Две библиотеки доски тянут шрифты мимо сборщика, и увидеть это можно только по
 * журналу сети:
 *
 *   • Excalidraw держит адреса шрифтов сцены обычными строками в своём JS —
 *     сборщик их не видит и не копирует. В работе путь берётся из
 *     `window.EXCALIDRAW_ASSET_PATH`, а если файла по нему нет, молча берётся
 *     зашитый запасной адрес на чужом CDN.
 *   • MathLive тянет шрифты KaTeX из своего каталога; путь задаётся
 *     `MathfieldElement.fontsDirectory` (`features/board/Formula.tsx`).
 *
 * Без своих копий обещание «наружу уходят только штрихи в распознаватель»
 * перестало бы быть правдой. Поэтому файлы кладутся в `public/` перед сборкой, а
 * оттуда их раздаёт тот же сервер, что и страницу.
 *
 * Запускается сам перед `vite build` (`package.json`, `scripts.build`).
 * Отдельным шагом, а не плагином Vite: копирование не зависит от режима сборки и
 * должно работать и тогда, когда собирают руками.
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const корень = dirname(dirname(fileURLToPath(import.meta.url)))
const публичный = join(корень, 'public')

/** Тринадцать мегабайт китайского Xiaolai не нужны: русскую доску им не пишут. */
const ПРОПУСТИТЬ = new Set(['Xiaolai'])

function копировать(откуда, куда) {
  if (!existsSync(откуда)) {
    // Пакета нет — область доски не собрана, и это законное состояние дерева.
    // Падать здесь значило бы ломать сборку всему сайту из-за одной области.
    console.warn(`шрифты: нет каталога ${откуда} — пропускаю`)
    return null
  }
  rmSync(куда, { recursive: true, force: true })
  mkdirSync(куда, { recursive: true })
  return куда
}

const excalidraw = join(корень, 'node_modules/@excalidraw/excalidraw/dist/prod/fonts')
const кудаExcalidraw = копировать(excalidraw, join(публичный, 'fonts'))
let семейств = 0
if (кудаExcalidraw) {
  for (const семья of readdirSync(excalidraw)) {
    if (ПРОПУСТИТЬ.has(семья)) continue
    cpSync(join(excalidraw, семья), join(кудаExcalidraw, семья), { recursive: true })
    семейств += 1
  }
}

const mathlive = join(корень, 'node_modules/mathlive/fonts')
const кудаMathlive = копировать(mathlive, join(публичный, 'mathlive-fonts'))
if (кудаMathlive) cpSync(mathlive, кудаMathlive, { recursive: true })

console.log(
  `шрифты: Excalidraw — ${семейств} семейств в public/fonts (Xiaolai пропущен), ` +
    `MathLive — ${кудаMathlive ? readdirSync(кудаMathlive).length : 0} файлов в public/mathlive-fonts`,
)
