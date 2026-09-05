/**
 * JobsMenu — очередь фоновых задач в шапке.
 *
 * Показывает то, что считается прямо сейчас, — за этим человек и лезет в
 * шапку. Список короткий и обновляется не таймером, а событиями потока
 * (`useUserEvents` сбрасывает ключ `jobs`), поэтому опроса здесь нет.
 *
 * Иконка — «отложенные действия», а не крутилка: крутилка в шапке читается как
 * «страница грузится» (замечание из правки 2 макетов).
 *
 * Вид задания называется по-русски тем же словарём, что у колокольчика
 * (`notifications.present.kindTitle`): служба зовёт виды по-английски
 * (`export`, `build`), и показывать её слова в шапке значило бы объяснять
 * человеку устройство очереди.
 */
import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api'
import { keys } from '@/api/queryKeys'
import { useT } from '@/i18n'
import { kindTitle } from '@/features/notifications/present'
import {
  Badge,
  Button,
  Icon,
  MenuContent,
  MenuItem,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
  Spinner,
} from '@/ui'

type JobCard = { id: string; kind: string; status: string; created_at: string }

function useActiveJobs() {
  return useQuery({
    queryKey: keys.jobs.list('active'),
    queryFn: async () => {
      // Служба фильтрует по одному состоянию за запрос, поэтому два запроса и
      // склейка здесь: «в работе» без «в очереди» — половина правды.
      const [running, queued] = await Promise.all([
        unwrap<{ jobs: JobCard[] }>(
          api.GET('/api/jobs', { params: { query: { status: 'running', limit: 20 } } }),
        ),
        unwrap<{ jobs: JobCard[] }>(
          api.GET('/api/jobs', { params: { query: { status: 'queued', limit: 20 } } }),
        ),
      ])
      return [...running.jobs, ...queued.jobs]
    },
    staleTime: 10_000,
  })
}

export function JobsMenu() {
  const t = useT()
  const { data } = useActiveJobs()
  const jobs = data ?? []

  return (
    <MenuRoot>
      <MenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          className="relative text-ink"
          aria-label={t('shell.jobs.label')}
        >
          <Icon name="tasks" size={18} />
          <Badge
            count={jobs.length}
            className="absolute -right-1 -top-1 h-[15px] min-w-[15px] px-1 text-[10px]"
          />
        </Button>
      </MenuTrigger>
      <MenuContent className="w-[340px] max-w-[calc(100vw-24px)]">
        <div className="px-2.5 py-1.5 text-xs uppercase tracking-wider text-muted">
          {t('shell.jobs.label')}
        </div>
        <MenuSeparator />
        {jobs.length === 0 && (
          <p className="px-2.5 py-s4 text-center text-sm text-muted">{t('shell.jobs.empty')}</p>
        )}
        {jobs.map((job) => (
          <MenuItem
            key={job.id}
            icon={
              job.status === 'running' ? (
                <Spinner size={16} />
              ) : (
                <Icon name="clock" size={18} className="text-muted" />
              )
            }
          >
            <span className="min-w-0 flex-1 truncate">{kindTitle(job.kind)}</span>
          </MenuItem>
        ))}
      </MenuContent>
    </MenuRoot>
  )
}
