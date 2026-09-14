/**
 * Formula — набранная формула: показ догадки и её правка.
 *
 * Один компонент, а не два. Правка человеком обязательна по устройству: ошибка
 * распознавания синтаксически безупречна (подменённая семёрка, потерянная
 * степень), ниже по течению её не поймает никто, а платит за проверку чужой
 * формулы тот, кто решал. Значит показ догадки и её правка — соседние состояния
 * одного места, и развести их по двум компонентам значит гарантировать, что они
 * разъедутся.
 *
 * **Почему MathLive, а не строка LaTeX.** Подтверждать `x^{2}+2x=8` человек не
 * станет — он этого не прочтёт; по набранной формуле подтверждение стоит одно
 * нажатие. Плюс строка приходит от чужого сервиса, то есть недоверенная, а
 * MathLive этой версии разбирает её без выхода за пределы своего поля.
 *
 * **Узел заводится руками, а не разметкой.** `math-field` — пользовательский
 * элемент, у него свои свойства (`readOnly`, `menuItems`, `value`), и ставить их
 * атрибутами нельзя: значением атрибута может быть только строка. Ссылка на
 * элемент нужна всё равно, так что и создаётся он здесь же.
 *
 * Пакет тяжёлый и нужен не каждому экрану, поэтому грузится отдельным куском по
 * требованию: доска без формул не платит за него временем загрузки.
 */
import { useEffect, useRef, useState } from 'react'

import { BASE_PATH } from '@/lib/basePath'
import { cn } from '@/lib/cn'

/** Поле MathLive в том объёме, в каком его трогает доска. */
type MathField = HTMLElement & {
  value: string
  readOnly: boolean
  menuItems: unknown[]
  mathVirtualKeyboardPolicy: string
}

let подключение: Promise<void> | null = null

/**
 * Подключить MathLive один раз на страницу.
 *
 * Шрифты берутся со своего сервера: иначе MathLive — второй, после редактора,
 * канал похода наружу, и обещание «наружу уходят только штрихи в распознаватель»
 * перестаёт быть правдой. Звуки нажатий выключены вовсе — доска не инструмент
 * ввода с клавиатуры, а поле правки открывается на секунду.
 */
function подключитьMathLive(): Promise<void> {
  подключение ??= import('mathlive').then((модуль) => {
    модуль.MathfieldElement.fontsDirectory = `${BASE_PATH}/mathlive-fonts`
    модуль.MathfieldElement.soundsDirectory = null
  })
  return подключение
}

export type FormulaProps = {
  /** Что показать. Пусто — поле пустое, но живое: в него можно набрать. */
  latex: string
  /** Правится ли формула прямо сейчас. Иначе — только чтение. */
  editable?: boolean
  /** Новое значение на каждое изменение поля. */
  onChange?: (latex: string) => void
  /** ⏎ в поле правки: запись должна быть жестом, а не путешествием. */
  onSubmit?: () => void
  /** Esc в поле правки: отказаться от набранного и вернуть прочитанное. */
  onCancel?: () => void
  className?: string
  /** Подпись для озвучки: формула сама по себе читается плохо. */
  label?: string
}

export function Formula({
  latex,
  editable = false,
  onChange,
  onSubmit,
  onCancel,
  className,
  label,
}: FormulaProps) {
  const гнездо = useRef<HTMLSpanElement | null>(null)
  const поле = useRef<MathField | null>(null)
  const [готово, setГотово] = useState(false)
  const [сбой, setСбой] = useState<string | null>(null)
  // Обработчики держатся ссылкой: слушатели вешаются один раз на живой элемент,
  // а пересоздавать их на каждый рендер значило бы снимать и вешать заново
  // посреди набора.
  const наПравку = useRef(onChange)
  наПравку.current = onChange
  const наВвод = useRef(onSubmit)
  наВвод.current = onSubmit
  const наОтказ = useRef(onCancel)
  наОтказ.current = onCancel

  useEffect(() => {
    let живо = true
    подключитьMathLive().then(
      () => живо && setГотово(true),
      (ошибка: unknown) => живо && setСбой(String(ошибка)),
    )
    return () => {
      живо = false
    }
  }, [])

  useEffect(() => {
    if (!готово || !гнездо.current || поле.current) return
    const узел = document.createElement('math-field') as MathField
    const наВход = () => наПравку.current?.(узел.value)
    // ⏎ записывает набранное, Esc отказывается от него. Оба события гасятся до
    // страницы: ⏎ иначе дошёл бы до формы, а Esc — до редактора, который снимает
    // им выделение, то есть правка формулы задевала бы рисунок.
    const наКлавишу = (со: KeyboardEvent) => {
      if (со.key !== 'Enter' && со.key !== 'Escape') return
      со.preventDefault()
      со.stopPropagation()
      if (со.key === 'Enter') наВвод.current?.()
      else наОтказ.current?.()
    }
    узел.addEventListener('input', наВход)
    узел.addEventListener('keydown', наКлавишу)
    гнездо.current.appendChild(узел)
    // Меню поля гасится ПОСЛЕ вставки в документ: до неё у элемента нет
    // внутреннего поля, и MathLive на этом свойстве бросает «Mathfield not
    // mounted» — а брошенное из эффекта исключение снимает с экрана всю
    // страницу целиком, не только формулу.
    try {
      узел.menuItems = []
    } catch {
      // Поле без меню — не беда: меню доске не нужно, а поле уже стоит.
    }
    поле.current = узел
    return () => {
      узел.removeEventListener('input', наВход)
      узел.removeEventListener('keydown', наКлавишу)
      узел.remove()
      поле.current = null
    }
  }, [готово])

  useEffect(() => {
    const узел = поле.current
    if (!узел) return
    узел.readOnly = !editable
    узел.mathVirtualKeyboardPolicy = editable ? 'auto' : 'manual'
    if (узел.value !== latex) узел.value = latex
    if (label) узел.setAttribute('aria-label', label)
    if (editable) узел.focus()
  }, [editable, latex, label, готово])

  if (сбой) {
    // Молчать нельзя: пустое место на месте формулы человек читает как «строки
    // нет», а она есть — просто её нечем нарисовать.
    return <span className={cn('font-mono text-xs text-err', className)}>{latex}</span>
  }
  return (
    <span
      ref={гнездо}
      className={cn(
        'block min-w-0 text-ink-strong [&_math-field]:block [&_math-field]:w-full',
        // Своей рамки и своего фона у поля нет: рамку рисует строка чистовика,
        // и вторая рамка внутри неё читалась бы как вложенное поле.
        '[&_math-field]:border-0 [&_math-field]:bg-transparent [&_math-field]:outline-none',
        className,
      )}
    >
      {!готово && <span className="font-mono text-xs text-muted">{latex}</span>}
    </span>
  )
}
