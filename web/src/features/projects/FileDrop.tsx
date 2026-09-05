/**
 * FileDrop — приёмник файлов: перетаскиванием и кнопкой.
 *
 * Одно и то же место используется трижды (шаблон нового проекта, материалы
 * проекта, утилита Word → PDF на дашборде), поэтому вид и поведение описаны
 * один раз.
 *
 * **Почему `<label>` вокруг настоящего `<input type="file">`, а не `<div>` с
 * `onClick`.** Скрытый input, которым управляет `ref`, теряет клавиатуру:
 * человек не может добраться до выбора файла табуляцией. Настоящий input под
 * `sr-only` остаётся в порядке табуляции, объявляется скринридером и открывает
 * то же самое окно выбора по пробелу — а перетаскивание висит на подписи.
 *
 * Счётчик `depth` вместо булева флага: `dragleave` приходит и при переходе
 * курсора на вложенный элемент, и рамка на подсветке мигала бы.
 */
import { useCallback, useId, useRef, useState, type DragEvent, type ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { Icon } from '@/ui'

export type FileDropProps = {
  onFiles: (files: File[]) => void
  /** Список расширений/типов для окна выбора, как у `<input accept>`. */
  accept?: string
  multiple?: boolean
  disabled?: boolean
  /** Крупная подпись внутри приёмника. */
  label: ReactNode
  /** Мелкая приписка под ней: что принимается и какой потолок размера. */
  hint?: ReactNode
  /** Низкий вид — для маленькой плитки утилиты. */
  compact?: boolean
  className?: string
}

export function FileDrop({
  onFiles,
  accept,
  multiple = false,
  disabled = false,
  label,
  hint,
  compact = false,
  className,
}: FileDropProps) {
  const inputId = useId()
  const depth = useRef(0)
  const [over, setOver] = useState(false)

  const take = useCallback(
    (list: FileList | null) => {
      const files = Array.from(list ?? [])
      if (files.length) onFiles(multiple ? files : files.slice(0, 1))
    },
    [multiple, onFiles],
  )

  const onDrop = useCallback(
    (event: DragEvent<HTMLLabelElement>) => {
      event.preventDefault()
      depth.current = 0
      setOver(false)
      if (!disabled) take(event.dataTransfer.files)
    },
    [disabled, take],
  )

  return (
    <label
      htmlFor={inputId}
      onDragEnter={(event) => {
        event.preventDefault()
        depth.current += 1
        if (!disabled) setOver(true)
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1)
        if (depth.current === 0) setOver(false)
      }}
      onDrop={onDrop}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-line-strong bg-surface-2 text-center transition-colors',
        compact ? 'px-s3 py-s4' : 'px-s4 py-s6',
        over && 'border-accent bg-accent-bg',
        disabled && 'cursor-not-allowed opacity-50',
        'focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent',
        className,
      )}
    >
      <input
        id={inputId}
        type="file"
        className="sr-only"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={(event) => {
          take(event.target.files)
          // Один и тот же файл, выбранный дважды подряд, иначе не даёт события.
          event.target.value = ''
        }}
      />
      <Icon name="file" size={compact ? 20 : 26} className="text-muted" />
      <span className="text-sm font-medium text-ink">{label}</span>
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  )
}
