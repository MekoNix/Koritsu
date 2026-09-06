/**
 * Avatar — картинка человека: своя, если он её загрузил, иначе генеративная.
 *
 * Правило интерфейса: «аватар генерируется из идентификатора пользователя, как
 * на GitHub; загрузка своей картинки — опционально, но дефолт всегда
 * генеративный». Генеративный поэтому рисуется здесь, в браузере, а не
 * запрашивается у службы: запрос за картинкой к постороннему сервису (gravatar
 * и подобные) — это утечка почты на чужой домен с каждой загрузки страницы.
 *
 * **Своя картинка — только по просьбе вызывающего.** `version` (это
 * `avatar_version` из профиля) больше нуля означает «на службе лежит картинка
 * этого человека», и тогда компонент показывает её вместо решётки. Без поля
 * рисуется генеративный — и это не догадка, а единственный честный ответ:
 * ходить за картинкой «на всякий случай» значило бы получать 404 на каждое имя
 * в списке участников.
 *
 * Версия едет в адресе (`?v=`) не для красоты: служба разрешает держать ответ
 * в кэше год, и без меняющегося адреса человек, заменивший картинку, до конца
 * года видел бы прежнюю.
 *
 * Не загрузилась (сеть, гонка с удалением) — показывается генеративный. Пустое
 * место вместо аватара человек читает как поломку страницы, а решётка из
 * идентификатора работает всегда.
 *
 * Как устроено. Из строки берётся 32-битный хеш (FNV-1a — короткий, без
 * зависимостей, и криптостойкость тут не нужна: подделка чужого аватара
 * ничего не даёт). Из хеша — тон в HSL и решётка 5×5, симметричная по
 * вертикали: половина считается по битам, вторая отражается. Ровно тот приём,
 * по которому узнаются identicon'ы GitHub.
 *
 * Цвет берётся HSL, а не из переменных темы: аватар обязан различать людей, а
 * акцент темы у всех один. Насыщенность и светлота подобраны так, чтобы пятно
 * читалось и на светлой, и на тёмной подложке.
 */
import { useMemo, useState } from 'react'

import { cn } from '@/lib/cn'
import { withBase } from '@/lib/basePath'

const CELLS = 5
const HALF = Math.ceil(CELLS / 2) // 3 колонки считаются, 2 отражаются

function hash32(text: string): number {
  // FNV-1a: две строки, четыре операции, устойчивое перемешивание младших бит.
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h >>> 0
}

export type AvatarProps = {
  /** Идентификатор человека. Пустой — рисуется нейтральное пятно. */
  id: string | null | undefined
  size?: number
  className?: string
  /** Подпись для скринридера; без неё аватар декоративен. */
  label?: string
  /**
   * `avatar_version` из профиля: больше нуля — у человека есть своя картинка,
   * и показывается она. Ноль, `null` или поля нет вовсе — генеративный.
   */
  version?: number | null
  /**
   * Готовый адрес картинки вместо собранного из `id` и `version`. Нужен
   * ровно одному месту — превью выбранного файла до отправки (`blob:`), — и
   * поэтому назван отдельно, а не спрятан в `version`.
   */
  src?: string | null
}

export function Avatar({ id, size = 32, className, label, version, src }: AvatarProps) {
  // Сорвавшуюся загрузку помним по адресу: сменился адрес — пробуем снова, и
  // замена картинки не остаётся навсегда за прошлой ошибкой.
  const [сорвалось, setСорвалось] = useState<string | null>(null)
  const адрес =
    src ??
    (id && version && version > 0
      ? withBase(`/api/users/${encodeURIComponent(id)}/avatar?v=${version}`)
      : null)

  const { hue, cells } = useMemo(() => {
    const h = hash32(id || 'koritsu')
    const grid: boolean[] = []
    for (let y = 0; y < CELLS; y += 1) {
      for (let x = 0; x < HALF; x += 1) {
        // Свой бит на каждую ячейку левой половины.
        grid.push(((h >>> ((y * HALF + x) % 30)) & 1) === 1)
      }
    }
    return { hue: h % 360, cells: grid }
  }, [id])

  const step = 100 / CELLS
  const squares = []
  for (let y = 0; y < CELLS; y += 1) {
    for (let x = 0; x < CELLS; x += 1) {
      const mirrored = x >= HALF ? CELLS - 1 - x : x
      if (!cells[y * HALF + mirrored]) continue
      squares.push(
        <rect
          key={`${x}-${y}`}
          x={x * step}
          y={y * step}
          width={step}
          height={step}
          fill={`hsl(${hue} 58% 55%)`}
        />,
      )
    }
  }

  return (
    <span
      className={cn(
        'inline-grid shrink-0 place-items-center overflow-hidden rounded-full border border-line bg-surface-2',
        className,
      )}
      style={{ width: size, height: size }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {адрес && сорвалось !== адрес ? (
        <img
          src={адрес}
          alt=""
          width={size}
          height={size}
          className="h-full w-full object-cover"
          onError={() => setСорвалось(адрес)}
        />
      ) : (
        <svg viewBox="0 0 100 100" width={size} height={size}>
          <rect width="100" height="100" fill={`hsl(${hue} 32% 92%)`} />
          {squares}
        </svg>
      )}
    </span>
  )
}
