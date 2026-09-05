/**
 * CopyButton — кнопка «скопировать».
 *
 * Успех показывается на самой кнопке, а не тостом: решение владельца — тосты
 * только на завершение фоновой задачи и на ошибку.
 */
import { useState } from 'react'

import { useT } from '@/i18n'

import { Button } from './Button'
import { Icon } from './Icon'

export function CopyButton({
  text,
  className,
  size = 'sm',
}: {
  text: string
  className?: string
  size?: 'sm' | 'md'
}) {
  const t = useT()
  const [done, setDone] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Буфер обмена может быть запрещён (нет https, отказано в праве). Тогда
      // остаётся выделение руками — ругаться на это человеку незачем.
      return
    }
    setDone(true)
    window.setTimeout(() => setDone(false), 1500)
  }

  return (
    <Button type="button" variant="secondary" size={size} className={className} onClick={copy}>
      <Icon name={done ? 'check' : 'copy'} size={16} />
      {done ? t('common.action.copied') : t('common.action.copy')}
    </Button>
  )
}
