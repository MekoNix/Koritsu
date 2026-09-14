/**
 * Ghosts — призраки: прочитанное стои́т **под своими росчерками**.
 *
 * ── Почему на холсте, а не в панели ──────────────────────────────────────────
 *
 * Чистовик сбоку заставляет сверять глазами две колонки и угадывать, какая
 * строка справа отвечает какой строке слева. Призрак снимает вопрос: под каждой
 * рукописной строкой стои́т набранная формула, которую из неё прочитали, — так
 * выглядит тетрадь с проверкой учителя. Подтверждать ничего не нужно: человек
 * видит, что прочитано, и правит либо росчерки, либо — нажатием на призрака —
 * сам текст.
 *
 * ── Почему призрак бледный ───────────────────────────────────────────────────
 *
 * Он читается вторым, а не первым: главное на доске — рукопись человека.
 * Половина непрозрачности оставляет формулу разборчивой и не даёт ей спорить с
 * записью над собой. Под указателем и в правке призрак становится полным: раз на
 * него смотрят, смотреть надо на него.
 *
 * ── Почему слой, а не элементы сцены ─────────────────────────────────────────
 *
 * Призрак — не часть рисунка: он пересчитывается вслед за росчерками и не должен
 * попадать ни в выделение, ни в ластик, ни в сохранение сцены, ни в
 * распознавание. Элемент сцены попадал бы во всё это сразу. Поэтому слой лежит
 * над полотнами редактора и следит за `scrollX`, `scrollY` и `zoom`: сцена
 * двигается — призраки едут вместе с ней.
 *
 * ── Почему `z-index` ровно 4 ─────────────────────────────────────────────────
 *
 * У редактора свой порядок слоёв: полотна — 1 и 2, слой островков UI (нижняя
 * панель, меню, зум) — 4. Контекста наложения его контейнер при этом **не
 * создаёт**: у `.excalidraw` стои́т `position: relative` без `z-index`, без
 * `isolation`, `transform` и `filter`, — значит наши числа и его числа
 * сравниваются напрямую, в одном контексте. Отсюда решение: слой призраков берёт
 * ровно 4 — число островков — и ставится в дереве **раньше** редактора. При
 * равном `z-index` порядок решает дерево: призраки встают над обоими полотнами и
 * уходят под островки. Число больше клало бы формулу поверх нижней панели,
 * меньше — под непрозрачное полотно, где её не видно вовсе.
 *
 * ── Как слой не отнимает перо ────────────────────────────────────────────────
 *
 * Сам слой событий не ловит вовсе (`pointer-events: none`), иначе под ним нельзя
 * было бы писать. Ловит их только сам призрак — полоска под строкой, — и место,
 * где начинают следующую строку, остаётся свободным.
 */

import type { CSSProperties } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { Formula } from './Formula'
import { LINE_STATES, type FairLine } from './recognizer'
import type { ViewState } from './strokes'
import type { Editing } from './TutorPanel'

/** Отступ призрака от нижнего края строки, в экранных пикселях. */
const ОТСТУП = 4

/**
 * Кегль призрака от высоты строки и запас по краям.
 *
 * Минимум — 12 px: мельче формула не читается вовсе, и «прочитано не то» на ней
 * уже не заметишь. Потолок нужен для одинокого крупного росчерка: без него
 * призрак вырастал бы в заголовок.
 */
const ДОЛЯ = 0.5
const МЕНЬШЕ = 12
const БОЛЬШЕ = 40

export type GhostsProps = {
  /** Строки чистовика вместе с их местом на сцене. */
  lines: readonly FairLine[]
  /** Прокрутка, масштаб и размер холста — прямо из `appState` редактора. */
  view: ViewState
  /** Строка, которую правят руками прямо сейчас; `null` — не правят ничего. */
  editing: Editing | null
  /** Нажатие на призрака: правка текста на месте. */
  onEdit: (id: string) => void
  onEditChange: (latex: string) => void
  onEditSave: () => void
  onEditCancel: () => void
  /** Наведение: та же подсветка, что и у строки в списке. */
  onHover?: (ids: string[] | null) => void
}

export function Ghosts({
  lines,
  view,
  editing,
  onEdit,
  onEditChange,
  onEditSave,
  onEditCancel,
  onHover,
}: GhostsProps) {
  const масштаб = view.zoom?.value ?? 1
  const ширина = view.width ?? 0
  const высота = view.height ?? 0

  return (
    <div
      className="pointer-events-none absolute inset-0 z-[4] overflow-hidden"
      data-testid="board-ghosts"
    >
      {lines.map((строка) => {
        // Координаты сцены → координаты холста. Те же, что у редактора, только
        // без смещения контейнера: слой лежит внутри него.
        const слева = (строка.box.x + (view.scrollX ?? 0)) * масштаб
        const сверху = (строка.box.y + строка.box.height + (view.scrollY ?? 0)) * масштаб + ОТСТУП
        if (ширина && (слева > ширина || сверху > высота || сверху < -40)) return null
        const кегль = Math.min(БОЛЬШЕ, Math.max(МЕНЬШЕ, строка.box.height * масштаб * ДОЛЯ))
        return (
          <Ghost
            key={строка.id}
            line={строка}
            editing={editing?.id === строка.id && editing.where === 'ghost' ? editing : null}
            style={{
              left: Math.round(слева),
              top: Math.round(сверху),
              fontSize: Math.round(кегль),
              maxWidth: Math.max(строка.box.width * масштаб, кегль * 8),
            }}
            onEdit={() => onEdit(строка.id)}
            onEditChange={onEditChange}
            onEditSave={onEditSave}
            onEditCancel={onEditCancel}
            onHover={onHover}
          />
        )
      })}
    </div>
  )
}

type GhostProps = {
  line: FairLine
  /** Не `null` — эту строку правят прямо сейчас, и призрак стал полем. */
  editing: Editing | null
  style: CSSProperties
  onEdit: () => void
  onEditChange: (latex: string) => void
  onEditSave: () => void
  onEditCancel: () => void
  onHover?: (ids: string[] | null) => void
}

/**
 * Один призрак: бледная формула под строкой, нажатие — правка её текста.
 *
 * Набранная руками строка — такой же призрак, только с крошечной пометкой:
 * рядом с росчерками она выглядит так же, как прочитанная, и это правда — под
 * строкой стои́т то, что в ней написано. Разница в одном: распознаватель её
 * больше не перезаписывает, и говорит об этом пометка, а не другой вид формулы.
 */
function Ghost({
  line,
  editing,
  style,
  onEdit,
  onEditChange,
  onEditSave,
  onEditCancel,
  onHover,
}: GhostProps) {
  const t = useT()
  const общий = 'absolute flex max-w-full items-center gap-1 rounded-sm px-1 leading-none'
  const руками = line.state === LINE_STATES.manual

  if (editing) {
    // В правке призрак становится полем и получает фон: набирать поверх
    // собственных росчерков нельзя — не видно ни курсора, ни набранного.
    return (
      <span
        data-state={line.state}
        data-editing="1"
        style={{ ...style, color: 'var(--ink-strong)' }}
        className={cn(общий, 'pointer-events-auto border border-accent bg-surface shadow-sm')}
      >
        <Formula
          latex={editing.latex}
          editable
          onChange={onEditChange}
          onSubmit={onEditSave}
          onCancel={onEditCancel}
          label={t('board.lines.title')}
        />
      </span>
    )
  }

  // Строки, которую не прочитали, призрак не рисует: пустая полоска под
  // росчерками читалась бы как «здесь ничего не написано». Такая строка видна в
  // списке словами «не разобрано» — вместе с кнопкой набрать её руками.
  if (!line.latex.trim()) return null

  return (
    <button
      type="button"
      data-state={line.state}
      // Ловит события только сам призрак: слой над холстом их не трогает, и
      // писать под ним можно всюду, кроме этой полоски.
      className={cn(
        общий,
        'pointer-events-auto cursor-text whitespace-nowrap border border-transparent',
        // Бледный, пока на него не смотрят. Формула внутри событий не ловит:
        // нажатие обязано попасть в призрака целиком, а не в поле MathLive.
        'opacity-50 hover:border-line-strong hover:opacity-100',
        '[&_math-field]:pointer-events-none',
        line.behind && 'border-dashed border-warn opacity-70',
      )}
      style={{ ...style, color: 'var(--ink-strong)' }}
      aria-label={t('board.ghost.edit')}
      title={line.behind ? t('board.ghost.behind') : t('board.ghost.edit')}
      onClick={onEdit}
      onPointerEnter={onHover ? () => onHover(line.strokes) : undefined}
      onPointerLeave={onHover ? () => onHover(null) : undefined}
    >
      <Formula latex={line.latex} label={t('board.lines.title')} />
      {руками && (
        <span className="text-[0.55em] uppercase tracking-wide" style={{ color: 'var(--accent)' }}>
          {t('board.ghost.manual')}
        </span>
      )}
    </button>
  )
}
