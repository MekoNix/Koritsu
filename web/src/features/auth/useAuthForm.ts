/**
 * useAuthError — раскладка отказа службы по форме.
 *
 * Служба говорит, ГДЕ беда (`where: "body.email"`), и это надо использовать:
 * ошибка, показанная под нужным полем, чинится с первого раза, а общая ошибка
 * наверху формы заставляет человека угадывать.
 *
 * Правило: есть `where` и такое поле в форме есть — ошибка идёт в поле; иначе
 * остаётся общей. Текст — всегда русский по коду (`errorText`).
 */
import { useCallback, useState } from 'react'
import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'

import { errorField, errorText } from '@/api/errors'

export function useAuthError<T extends FieldValues>(setError: UseFormSetError<T>) {
  const [formError, setFormError] = useState<string | null>(null)

  const reset = useCallback(() => setFormError(null), [])

  const handle = useCallback(
    (error: unknown, fields: readonly string[]) => {
      const field = errorField(error)
      const text = errorText(error)
      if (field && fields.includes(field)) {
        setError(field as Path<T>, { type: 'server', message: text })
        setFormError(null)
        return
      }
      setFormError(text)
    },
    [setError],
  )

  return { formError, handle, reset }
}
