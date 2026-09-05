/**
 * SearchPalette — поиск по Ctrl+K.
 *
 * Решение владельца: «поиск Ctrl+K — по проектам и материалам». Палитра, а не
 * страница результатов: ищут, чтобы уйти отсюда куда-то, и лишний экран между
 * вопросом и ответом здесь только мешает.
 *
 * Вид — из макета `01-shell` (`.palette` в `assets/base.css`): окно шириной
 * 640, прижатое к верху, поле ввода вместо заголовка, список под ним. Окно
 * собрано на примитивах Radix, а не на общем `ui/Dialog`, ровно из-за этого:
 * у общего окна есть шапка с заголовком и крестиком, а у палитры её нет —
 * заголовком служит само поле.
 *
 * Клавиатура: стрелки водят по списку, `Enter` открывает выбранное, `Esc`
 * закрывает (это Radix). Мышь и клавиатура ведут один и тот же список, поэтому
 * подсветка — одно состояние, а не два.
 *
 * Пустое состояние тут двух родов, и путать их нельзя: «наберите» (ещё ничего
 * не набрано) и «ничего не нашлось» (набрано, но не совпало).
 */
import * as RadixDialog from '@radix-ui/react-dialog'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { ErrorState, Icon, SkeletonLines } from '@/ui'

import { useSearchIndex } from './data'
import { currentProjectId, filterHits, type Hit } from './filter'

export function SearchPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const t = useT()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const списокRef = useRef<HTMLUListElement>(null)

  const projectId = currentProjectId(pathname)
  const { hits, isLoading, error } = useSearchIndex(open, projectId, t('workspace.personalName'))
  const found = useMemo(() => filterHits(hits, query), [hits, query])

  // Закрылась — забыть набранное: палитра открывается за ответом на новый
  // вопрос, а не за прошлым.
  useEffect(() => {
    if (!open) {
      setQuery('')
      setActive(0)
    }
  }, [open])

  useEffect(() => {
    setActive(0)
  }, [query])

  // Выбранное держим в поле зрения: стрелка вниз на десятой строке иначе
  // уводит выбор за нижний край списка.
  useEffect(() => {
    const строка = списокRef.current?.children[active] as HTMLElement | undefined
    строка?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const открыть = (hit: Hit | undefined) => {
    if (!hit) return
    onOpenChange(false)
    navigate(hit.to)
  }

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-[100] bg-overlay" />
        <RadixDialog.Content
          aria-label={t('search.title')}
          className={cn(
            'fixed left-1/2 top-[12vh] z-[101] w-[min(640px,calc(100vw-24px))] -translate-x-1/2',
            'overflow-hidden rounded-lg border border-line bg-elevated shadow-2 backdrop-blur-theme',
          )}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setActive((n) => (found.length ? (n + 1) % found.length : 0))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((n) => (found.length ? (n - 1 + found.length) % found.length : 0))
            } else if (e.key === 'Enter') {
              e.preventDefault()
              открыть(found[active])
            }
          }}
        >
          {/* Заголовок нужен скринридеру, но виден быть не должен: заголовок
              палитры — это её поле ввода. */}
          <RadixDialog.Title className="sr-only">{t('search.title')}</RadixDialog.Title>

          <div className="relative flex items-center border-b border-line">
            <span className="pointer-events-none absolute left-3.5 text-muted" aria-hidden="true">
              <Icon name="search" size={20} />
            </span>
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('search.placeholder')}
              aria-label={t('search.placeholder')}
              role="combobox"
              aria-expanded
              aria-controls="search-results"
              className="min-h-[50px] w-full bg-transparent pl-11 pr-3 text-md text-ink outline-none placeholder:text-muted"
            />
          </div>

          <div className="max-h-[360px] overflow-auto p-1">
            {isLoading && (
              <div className="p-s3">
                <SkeletonLines count={3} />
              </div>
            )}
            {!!error && !isLoading && <ErrorState error={error} />}
            {!isLoading && !error && !query.trim() && (
              <p className="px-3 py-s4 text-center text-sm text-muted">{t('search.hint')}</p>
            )}
            {!isLoading && !error && !!query.trim() && found.length === 0 && (
              <p className="px-3 py-s4 text-center text-sm text-muted">
                {t('search.nothing', { query: query.trim() })}
              </p>
            )}
            <ul id="search-results" role="listbox" ref={списокRef} className="flex flex-col">
              {found.map((hit, i) => (
                <li
                  key={`${hit.kind}:${hit.id}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => открыть(hit)}
                  className={cn(
                    'flex cursor-pointer items-center gap-s2 rounded-sm px-2.5 py-2 text-sm',
                    i === active ? 'bg-surface-2 text-ink-strong' : 'text-ink',
                  )}
                >
                  <Icon
                    name={hit.kind === 'project' ? 'folder' : 'file'}
                    size={18}
                    className="shrink-0 text-muted"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{hit.name}</span>
                    <span className="block truncate text-xs text-muted">
                      {hit.kind === 'project'
                        ? t('search.inWorkspace', { name: hit.workspace })
                        : t('search.inProject', { name: hit.project })}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-muted">
                    {t(`search.kind.${hit.kind}`)}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex items-center gap-s3 border-t border-line bg-surface-2 px-3 py-1.5 text-xs text-muted">
            <span>{t('search.keys.move')}</span>
            <span>{t('search.keys.open')}</span>
            <span>{t('search.keys.close')}</span>
            {projectId === null && <span className="ml-auto">{t('search.materialsHint')}</span>}
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}
