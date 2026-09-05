// Несуществующий адрес внутри оболочки. Ссылка «в никуда» — ошибка, а не
// пустая страница: так её видно и человеку, и сквозному тесту.
import { Link } from 'react-router-dom'

import { useT } from '@/i18n'
import { Button, EmptyState } from '@/ui'

export function NotFoundPage() {
  const t = useT()
  return (
    <EmptyState
      icon="info"
      title={t('common.state.notFound')}
      text={t('common.state.notFoundHint')}
      action={
        <Button asChild variant="secondary">
          <Link to="/">{t('shell.nav.dashboard')}</Link>
        </Button>
      }
    />
  )
}
