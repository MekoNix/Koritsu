/**
 * paletteCheck — вычислимые проверки палитры графиков. Только для теста.
 *
 * Перенос `scripts/validate_palette.js` из skill `dataviz` (те же формулы, те
 * же пороги, те же имена проверок). Перенос, а не запуск оригинала, потому что
 * оригинал живёт вне репозитория: палитра тем лежит здесь и правится здесь,
 * значит и мерка обязана лежать рядом с ней и ехать вместе с ней. Проверяет её
 * `palette.test.ts` — по всем восьми сочетаниям тема × режим.
 *
 * Что считается (нумерация — из skill):
 *
 *   2. полоса светлоты — OKLCH L внутри полосы режима;
 *   3. пол хромы — OKLCH C ≥ 0.10, ниже цвет читается как серый;
 *   4. различимость при дальтонизме — ΔE в OKLab ×100 между парами при
 *      симуляции протанопии и дейтеранопии (Machado, Oliveira & Fernandes 2009,
 *      сила 1.0); цель 8, пол 6;
 *   4б. пол обычного зрения — то же ΔE без симуляции, порог 15: соседние цвета
 *      обязаны различаться и тем, кто видит все;
 *   5. контраст к поверхности — WCAG ≥ 3:1.
 *
 * Проверки 1 (порядок семейств тонов) и 6 (значения из описанной палитры) —
 * правила устройства, а не измерения; их держит `themes.css` и подбор.
 *
 * Проверяются ВСЕ пары, а не только соседние: у графиков админки нет одного
 * порядка рядов (столбцы по дням, горизонтальные полосы по видам, легенда), и
 * любые два цвета могут оказаться рядом.
 */

// ── пороги (те же числа, что в skill) ────────────────────────────────────────
const ПОЛОСА = { light: [0.43, 0.77], dark: [0.48, 0.67] } as const
const ПОЛ_ХРОМЫ = 0.1
const ЦЕЛЬ_CVD = 8.0
const ПОЛ_ОБЫЧНОГО = 15.0
const МИН_КОНТРАСТ = 3.0

/** Матрицы симуляции дальтонизма (Machado, Oliveira & Fernandes 2009, 1.0). */
const MACHADO = {
  protan: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deutan: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
} as const

export type CvdKind = keyof typeof MACHADO

// ── преобразования цвета ─────────────────────────────────────────────────────
function срез(hex: string): [number, number, number] {
  const h = hex.trim().replace(/^#/, '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as [number, number, number]
}

const в_линейный = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)

function линейный(hex: string): [number, number, number] {
  const [r, g, b] = срез(hex)
  return [в_линейный(r), в_линейный(g), в_линейный(b)]
}

function светимость(hex: string): number {
  const [r, g, b] = линейный(hex)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** Отношение контраста по WCAG. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [светимость(a), светимость(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

function oklabИзЛинейного([r, g, b]: [number, number, number]): [number, number, number] {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

/** OKLCH: светлота и хрома (тон здесь не нужен ни одной проверке). */
export function oklch(hex: string): { L: number; C: number } {
  const [L, a, b] = oklabИзЛинейного(линейный(hex))
  return { L, C: Math.hypot(a, b) }
}

function симулировать(hex: string, вид: CvdKind): [number, number, number] {
  const [r, g, b] = линейный(hex)
  const M = MACHADO[вид]
  const в_границах = (v: number) => Math.max(0, Math.min(1, v))
  return [
    в_границах(M[0][0] * r + M[0][1] * g + M[0][2] * b),
    в_границах(M[1][0] * r + M[1][1] * g + M[1][2] * b),
    в_границах(M[2][0] * r + M[2][1] * g + M[2][2] * b),
  ]
}

/** Расстояние в OKLab ×100. Без `вид` — обычное зрение. */
export function deltaE(a: string, b: string, вид?: CvdKind): number {
  const п = oklabИзЛинейного(вид ? симулировать(a, вид) : линейный(a))
  const в = oklabИзЛинейного(вид ? симулировать(b, вид) : линейный(b))
  return 100 * Math.hypot(п[0] - в[0], п[1] - в[1], п[2] - в[2])
}

// ── сами проверки ────────────────────────────────────────────────────────────
export type CheckName = 'lightness' | 'chroma' | 'cvd' | 'normal' | 'contrast'

export type CheckResult = { name: CheckName; pass: boolean; detail: string }

/** Все пары индексов палитры: любые два цвета могут оказаться рядом. */
function пары(n: number): [number, number][] {
  const out: [number, number][] = []
  for (let i = 0; i < n; i += 1) for (let j = i + 1; j < n; j += 1) out.push([i, j])
  return out
}

export function validatePalette(
  palette: readonly string[],
  { mode, surface }: { mode: 'light' | 'dark'; surface: string },
): CheckResult[] {
  const [низ, верх] = ПОЛОСА[mode]
  const список = пары(palette.length)
  const цвет = (i: number) => palette[i] as string

  const вне = palette.filter((c) => {
    const { L } = oklch(c)
    return L < низ || L > верх
  })

  const бледные = palette.filter((c) => oklch(c).C < ПОЛ_ХРОМЫ)

  let худший_cvd: { d: number; пара: string } = { d: Infinity, пара: '' }
  for (const вид of ['protan', 'deutan'] as CvdKind[]) {
    for (const [i, j] of список) {
      const d = deltaE(цвет(i), цвет(j), вид)
      if (d < худший_cvd.d) худший_cvd = { d, пара: `${цвет(i)}↔${цвет(j)} (${вид})` }
    }
  }

  let худший_обычный: { d: number; пара: string } = { d: Infinity, пара: '' }
  for (const [i, j] of список) {
    const d = deltaE(цвет(i), цвет(j))
    if (d < худший_обычный.d) худший_обычный = { d, пара: `${цвет(i)}↔${цвет(j)}` }
  }

  const тусклые = palette.filter((c) => contrast(c, surface) < МИН_КОНТРАСТ)

  return [
    {
      name: 'lightness',
      pass: вне.length === 0,
      detail: вне.length ? `вне полосы ${низ}–${верх}: ${вне.join(', ')}` : `все ${palette.length}`,
    },
    {
      name: 'chroma',
      pass: бледные.length === 0,
      detail: бледные.length ? `ниже ${ПОЛ_ХРОМЫ}: ${бледные.join(', ')}` : `все ${palette.length}`,
    },
    {
      name: 'cvd',
      pass: худший_cvd.d >= ЦЕЛЬ_CVD,
      detail: `худшая пара ${худший_cvd.пара} ΔE ${худший_cvd.d.toFixed(1)}`,
    },
    {
      name: 'normal',
      pass: худший_обычный.d >= ПОЛ_ОБЫЧНОГО,
      detail: `худшая пара ${худший_обычный.пара} ΔE ${худший_обычный.d.toFixed(1)}`,
    },
    {
      name: 'contrast',
      pass: тусклые.length === 0,
      detail: тусклые.length
        ? `ниже ${МИН_КОНТРАСТ}:1 к ${surface}: ${тусклые.join(', ')}`
        : `все ${palette.length}`,
    },
  ]
}
