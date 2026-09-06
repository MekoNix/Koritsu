/**
 * ReportThumb — картинка на карточке: первая страница собранного документа или
 * набросок вместо неё.
 *
 * **Настоящая страница показывается, когда она есть.** Сборка кладёт PNG первой
 * страницы PDF отдельным артефактом и записывает его у запуска
 * (`packages/api/runs/handlers/build.py`), поэтому картинка не пропадает после
 * перезагрузки и не требует запускать LibreOffice ради списка. Отчёт, который
 * ещё ни разу не собирали, показывается наброском: пустой прямоугольник на
 * карточке читался бы как «документ пуст», а он просто не собран.
 *
 * Набросок — не рендер и не притворяется им: строки-заглушки раскладываются по
 * идентификатору, как генеративный аватар у человека, и у одной карточки он
 * всегда один и тот же, поэтому список не мельтешит при перерисовке.
 */
import { useMemo } from 'react'

export function ReportThumb({ seed, src, alt }: { seed: string; src?: string; alt?: string }) {
  const строки = useMemo(() => набросок(seed), [seed])

  if (src) {
    return (
      <img
        src={src}
        alt={alt ?? ''}
        loading="lazy"
        // `bg-surface` под картинкой обязателен: страница документа белая, и на
        // тёмной теме её поля иначе просвечивали бы фоном карточки.
        className="aspect-[1/1.05] w-full border-b border-line bg-surface object-cover object-top"
      />
    )
  }

  return (
    <div
      aria-hidden="true"
      className="flex aspect-[1/1.05] flex-col gap-[6%] border-b border-line bg-surface-2 p-[14%]"
    >
      <span className="mx-auto mb-[4%] h-1.5 w-3/5 rounded-full bg-line-strong opacity-90" />
      {строки.map((ширина, i) => (
        <span
          key={i}
          className="h-[3px] rounded-full bg-line-strong opacity-60"
          style={{ width: `${ширина}%` }}
        />
      ))}
    </div>
  )
}

/** Ширины строк наброска: те же на одном идентификаторе, разные на разных. */
function набросок(seed: string): number[] {
  let число = 0
  for (const знак of seed) число = (число * 31 + знак.charCodeAt(0)) % 100000
  return Array.from({ length: 7 }, (_, i) => {
    число = (число * 1103515245 + 12345) % 2147483648
    return 45 + ((число >> (i + 3)) % 50)
  })
}
