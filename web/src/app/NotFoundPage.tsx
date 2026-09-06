// Несуществующий адрес внутри оболочки. Ссылка «в никуда» — ошибка, а не
// пустая страница: так её видно и человеку, и сквозному тесту.
//
// Выходов два, и оба нужны. Дашборд — ответ на «я не туда попал»; список работ
// — на «работа была здесь»: по битой ссылке на работу человек приходит именно
// за ней, и отправлять его отсюда на дашборд значит заставить искать заново.
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
        <div className="flex flex-wrap items-center justify-center gap-s2">
          <Button asChild variant="secondary">
            <Link to="/projects">{t('common.error.toProjects')}</Link>
          </Button>
          <Button asChild variant="ghost">
            <Link to="/">{t('shell.nav.dashboard')}</Link>
          </Button>
        </div>
      }
    />
  )
}
