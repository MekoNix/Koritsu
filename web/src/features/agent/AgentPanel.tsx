/**
 * AgentPanel — окно агента: выдвижная панель справа поверх любого экрана.
 *
 *     Почему панель, а не страница и не модалка
 *     -----------------------------------------
 *
 * Бриф: «не отдельная страница, а всплывающее окно поверх текущего экрана, где
 * пишешь, что поменять». Решение владельца (§3 третьего круга) уточняет форму:
 * выдвижная панель справа, **не модальная**. Отсюда всё устройство:
 *
 * * `Radix Dialog` с `modal={false}` и без затемнения: экран под панелью
 *   остаётся живым — по нему можно листать теги и смотреть, что изменилось,
 *   пока агент работает. Radix при этом даёт то, что легко забыть и невозможно
 *   заметить глазами: `Esc`, возврат фокуса на кнопку в шапке, `aria-modal` в
 *   правильном значении;
 * * щелчок мимо панель НЕ закрывает (`onInteractOutside` отменяется). Иначе
 *   первый же клик по экрану под ней — то, ради чего немодальность и заводилась,
 *   — убивал бы прогон из виду;
 * * панель монтирована всегда, а не только когда открыта: `Ctrl+J` обязан
 *   работать с любого экрана, а прогон — продолжаться после закрытия окна
 *   («работает в фоне» из макета). Пока панель закрыта, она не рисует ничего и
 *   не спрашивает службу ни о чём.
 *
 * Контекст — работа из адреса экрана под панелью (`context.ts`); вне работы
 * панель спрашивает её сама.
 */
import * as RadixDialog from '@radix-ui/react-dialog'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { useCurrentWorkspace, useUsage } from '@/api/hooks'
import { useT } from '@/i18n'
import { useHotkey } from '@/lib/hotkeys'
import { Button, EmptyState, Icon, Select, Textarea } from '@/ui'
import { useProject, useProjects } from '@/features/projects/data'
import { defaultProvider, useProviders } from '@/features/reports/data'
import { ModelPicker, PriceHint } from '@/features/reports/runControls'

import { AgentHistory } from './AgentHistory'
import { AgentRunView } from './AgentRunView'
import { closeAgentPanel, openAgentPanel, toggleAgentPanel, useAgentPanelOpen } from './panelStore'
import { projectFromPath } from './context'
import { AGENT, TASK_MAX } from './types'
import { useAgentRun, type AgentRunState } from './useAgentRun'

export function AgentPanel() {
  const t = useT()
  const open = useAgentPanelOpen()
  const location = useLocation()

  // Горячая клавиша живёт здесь, а не в шапке: панель монтирована всегда, а
  // шапка — только внутри оболочки, и на экранах входа её нет вовсе.
  useHotkey('ctrl+j', toggleAgentPanel)

  const изАдреса = projectFromPath(location.pathname)
  const [выбранный, setВыбранный] = useState<string | null>(null)
  const projectId = изАдреса ?? выбранный

  const [endpoint, setEndpoint] = useState<string | null>(null)
  const [task, setTask] = useState('')
  const [overwrite, setOverwrite] = useState(false)

  // Прогон — на верхнем уровне: он обязан пережить закрытие панели.
  const run = useAgentRun(projectId, endpoint, overwrite)

  return (
    <RadixDialog.Root
      open={open}
      onOpenChange={(next) => (next ? openAgentPanel() : closeAgentPanel())}
      modal={false}
    >
      <RadixDialog.Portal>
        <RadixDialog.Content
          aria-describedby={undefined}
          onInteractOutside={(event) => event.preventDefault()}
          className={
            'fixed bottom-0 right-0 top-0 z-[90] flex w-[min(420px,100vw)] flex-col ' +
            'border-l border-agent bg-elevated shadow-2 backdrop-blur-theme'
          }
        >
          <header className="flex items-center gap-s2 border-b border-line px-s4 py-s3">
            <Icon name="agent" size={18} className="text-agent" />
            <RadixDialog.Title className="flex-1 font-display text-md font-semibold text-ink-strong">
              {t('agent.title')}
            </RadixDialog.Title>
            <kbd className="rounded-sm border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
              Ctrl J
            </kbd>
            <RadixDialog.Close asChild>
              <Button variant="ghost" size="sm" iconOnly aria-label={t('agent.close')}>
                <Icon name="close" size={16} />
              </Button>
            </RadixDialog.Close>
          </header>

          <PanelBody
            projectId={projectId}
            fromPath={!!изАдреса}
            onPickProject={setВыбранный}
            endpoint={endpoint}
            onEndpoint={setEndpoint}
            task={task}
            onTask={setTask}
            overwrite={overwrite}
            onOverwrite={setOverwrite}
            run={run}
          />
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}

type BodyProps = {
  projectId: string | null
  /** Работа взята из адреса — значит выбирать её в панели незачем. */
  fromPath: boolean
  onPickProject: (id: string) => void
  endpoint: string | null
  onEndpoint: (endpoint: string) => void
  task: string
  onTask: (task: string) => void
  overwrite: boolean
  onOverwrite: (value: boolean) => void
  run: AgentRunState
}

/**
 * Содержимое панели. Отдельным компонентом, потому что `Radix` рисует его
 * только когда панель открыта: закрытая панель не должна спрашивать службу о
 * проектах, пресетах и расходе на каждом экране сайта.
 */
function PanelBody({
  projectId,
  fromPath,
  onPickProject,
  endpoint,
  onEndpoint,
  task,
  onTask,
  overwrite,
  onOverwrite,
  run,
}: BodyProps) {
  const t = useT()
  const project = useProject(projectId ?? undefined)
  const providers = useProviders()
  const usage = useUsage()
  const поле = useRef<HTMLTextAreaElement>(null)

  // Пресет по умолчанию: сначала свой ключ, потом общий (`defaultProvider`).
  useEffect(() => {
    if (endpoint !== null) return
    const умолчание = defaultProvider(providers.data)
    if (умолчание) onEndpoint(умолчание)
  }, [providers.data, endpoint, onEndpoint])

  // Фокус в поле при открытии: панель открывают, чтобы писать в неё.
  useEffect(() => {
    поле.current?.focus()
  }, [])

  const занято = run.running || run.starting
  const можно = !!projectId && !!endpoint && !!task.trim() && !занято

  const запустить = () => {
    if (!можно) return
    run.start(task)
  }

  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-s4 overflow-y-auto p-s4">
        {/* Над какой работой стоим. */}
        {projectId ? (
          <p className="truncate text-xs text-muted">
            {t('agent.project.label')}{' '}
            <span className="text-ink">{project.data?.name ?? projectId}</span>
          </p>
        ) : (
          <ProjectPicker onPick={onPickProject} />
        )}

        {!fromPath && projectId && (
          <p className="text-xs text-muted">{t('agent.project.chosen')}</p>
        )}

        <AgentRunView run={run} projectId={projectId ?? ''} />

        {projectId && <AgentHistory projectId={projectId} onRepeat={onTask} />}
      </div>

      <footer className="flex flex-col gap-s2 border-t border-line bg-surface-2 p-s3">
        <div className="flex flex-wrap items-center justify-between gap-s2 text-xs text-muted">
          <ModelPicker
            providers={providers.data}
            value={endpoint}
            onChange={onEndpoint}
            disabled={занято}
          />
          <PriceHint kind={AGENT} usage={usage.data} />
        </div>

        <Textarea
          ref={поле}
          label={t('agent.task.label')}
          hint={занято ? t('agent.task.busy') : t('agent.task.hint')}
          placeholder={t('agent.task.placeholder')}
          maxLength={TASK_MAX}
          value={task}
          disabled={занято}
          onChange={(e) => onTask(e.target.value)}
          onKeyDown={(e) => {
            // Ctrl+Enter — запустить. Обычный Enter оставлен переносу строки:
            // задача агенту бывает в несколько предложений.
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault()
              запустить()
            }
          }}
          className="min-h-[72px]"
        />

        <label className="flex items-center gap-s2 text-xs text-muted">
          <input
            type="checkbox"
            checked={overwrite}
            disabled={занято}
            onChange={(e) => onOverwrite(e.target.checked)}
          />
          {t('agent.overwrite')}
        </label>

        <div className="flex items-center gap-s2">
          {run.running ? (
            <Button variant="secondary" size="sm" onClick={run.cancel}>
              <Icon name="close" size={14} />
              {t('agent.stop')}
            </Button>
          ) : (
            <Button variant="agent" size="sm" disabled={!можно} onClick={запустить}>
              <Icon name="agent" size={14} />
              {t('agent.run')}
            </Button>
          )}
          {!!run.lastTask && !run.running && (
            <Button variant="ghost" size="sm" onClick={run.regenerate}>
              <Icon name="refresh" size={14} />
              {t('agent.regenerate')}
            </Button>
          )}
        </div>
      </footer>
    </>
  )
}

/**
 * Выбор работы, когда панель открыли вне её.
 *
 * Список — текущего пространства (`useCurrentWorkspace`), а не личного: у
 * человека их бывает несколько, и работа, которую он видит на экране, лежит в
 * том, что выбрано в шапке.
 */
function ProjectPicker({ onPick }: { onPick: (id: string) => void }) {
  const t = useT()
  const workspace = useCurrentWorkspace()
  const projects = useProjects(workspace.data?.id)
  const список = projects.data ?? []

  if (projects.isSuccess && !список.length) {
    return (
      <EmptyState
        compact
        icon="folder"
        title={t('agent.project.emptyTitle')}
        text={t('agent.project.emptyText')}
        action={
          <Button asChild variant="secondary" size="sm">
            <Link to="/projects">{t('agent.project.toProjects')}</Link>
          </Button>
        }
      />
    )
  }

  return (
    <Select
      label={t('agent.project.pick')}
      hint={t('agent.project.pickHint')}
      defaultValue=""
      onChange={(e) => e.target.value && onPick(e.target.value)}
    >
      <option value="" disabled>
        {t('agent.project.none')}
      </option>
      {список.map((проект) => (
        <option key={проект.id} value={проект.id}>
          {проект.name}
        </option>
      ))}
    </Select>
  )
}
