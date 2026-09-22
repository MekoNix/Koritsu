/**
 * ModelCombobox — выбор модели поставщика: поле с поиском, а не список.
 *
 * Обычный `<select>` здесь не годится, и причина не в красоте. Список приходит
 * от самого поставщика, и длина его от поставщика и зависит: у Anthropic это
 * десяток имён, у OpenRouter — сотни. Родной список на сотне пунктов
 * пролистывается вслепую: имена в нём длинные, похожие и отличаются хвостом
 * («…-flash-lite», «…-flash-lite-preview»), а искать в нём можно только набором
 * первых букв, который сбрасывается через секунду.
 *
 * Поэтому здесь поле ввода поверх списка: набираешь кусок имени — остаются
 * совпадения, стрелки водят, `Enter` выбирает, `Esc` закрывает. Совпадение
 * ищется и по идентификатору, и по человеческому имени: человек помнит модель
 * то как «Sonnet», то как `claude-sonnet-5`.
 *
 * **Набранное, которого нет в списке, — законный выбор.** Каталог поставщика
 * бывает неполным (`deepseek-chat` работает и в `/v1/models` не значится), и
 * запретить незнакомое имя значило бы отобрать работающую модель. Поэтому у
 * непустого поиска без совпадений есть свой пункт — «взять как есть».
 *
 * **Пустое значение — «как в пресете»**, и это не «ничего не выбрано»: это
 * умолчание, с которым человек работал до появления выбора. Оно стоит первым
 * пунктом, а не прячется в очистке поля.
 */
import * as Popover from '@radix-ui/react-popover'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon, Spinner } from '@/ui'

import type { ProviderModel } from './types'

export function ModelCombobox({
  value,
  models,
  loading,
  disabled,
  onChange,
  label,
  id,
}: {
  /** Выбранное имя модели. Пусто — умолчание пресета. */
  value: string
  models: ProviderModel[]
  loading?: boolean
  disabled?: boolean
  onChange: (model: string) => void
  label: string
  id: string
}) {
  const t = useT()
  const [открыто, setОткрыто] = useState(false)
  const [запрос, setЗапрос] = useState('')
  const [активный, setАктивный] = useState(0)
  const списокРеф = useRef<HTMLUListElement>(null)

  const найденные = useMemo(() => {
    const игла = запрос.trim().toLowerCase()
    if (!игла) return models
    return models.filter(
      (м) => м.id.toLowerCase().includes(игла) || м.title.toLowerCase().includes(игла),
    )
  }, [models, запрос])

  // Пункты одним списком, в том же порядке, в каком они на экране: стрелки и
  // мышь обязаны вести один и тот же список, иначе подсветка и выбор разъезжаются.
  const пункты = useMemo(() => {
    const свои: { key: string; model: string; title: string; note?: string }[] = []
    if (!запрос.trim()) {
      свои.push({ key: '', model: '', title: t('settings.providers.modelDefault') })
    }
    for (const м of найденные) {
      свои.push({ key: м.id, model: м.id, title: м.title, note: м.title === м.id ? '' : м.id })
    }
    const набрано = запрос.trim()
    if (набрано && !найденные.some((м) => м.id === набрано)) {
      свои.push({
        key: `:как-есть:${набрано}`,
        model: набрано,
        title: t('settings.providers.asIs', { name: набрано }),
      })
    }
    return свои
  }, [найденные, запрос, t])

  // Открылись — поиск чистый, подсветка на выбранном: список, открывшийся
  // с прошлым запросом, показывает не то, что человек ожидает увидеть.
  useEffect(() => {
    if (!открыто) return
    setЗапрос('')
    const где = models.findIndex((м) => м.id === value)
    setАктивный(где >= 0 ? где + 1 : 0)
  }, [открыто, models, value])

  useEffect(() => {
    setАктивный(0)
  }, [запрос])

  useEffect(() => {
    списокРеф.current?.children[активный]?.scrollIntoView({ block: 'nearest' })
  }, [активный])

  const выбрать = (model: string) => {
    onChange(model)
    setОткрыто(false)
  }

  const поКлавише = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setАктивный((был) => {
        const шаг = e.key === 'ArrowDown' ? 1 : -1
        const всего = пункты.length || 1
        return (был + шаг + всего) % всего
      })
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const пункт = пункты[активный]
      if (пункт) выбрать(пункт.model)
    }
  }

  const показ = value || t('settings.providers.modelDefault')

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      <Popover.Root open={открыто} onOpenChange={setОткрыто}>
        <Popover.Trigger asChild>
          <button
            id={id}
            type="button"
            role="combobox"
            aria-expanded={открыто}
            disabled={disabled}
            className={cn(
              'flex min-h-[36px] w-full items-center gap-s2 rounded-sm border border-line-strong bg-surface px-3 py-2 text-left text-sm',
              'focus:border-accent focus:outline-none focus:ring-[3px] focus:ring-accent-bg',
              'disabled:cursor-not-allowed disabled:opacity-50',
              value ? 'font-mono text-ink' : 'text-muted',
            )}
          >
            <span className="min-w-0 flex-1 truncate">{показ}</span>
            {loading ? <Spinner size={14} /> : <Icon name="search" size={14} className="text-muted" />}
          </button>
        </Popover.Trigger>

        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={4}
            className="z-[60] w-[var(--radix-popover-trigger-width)] rounded-md border border-line bg-elevated p-1 shadow-2 backdrop-blur-theme"
          >
            <div className="flex items-center gap-s2 border-b border-line px-2 pb-1.5 pt-1">
              <Icon name="search" size={14} className="shrink-0 text-muted" />
              <input
                autoFocus
                value={запрос}
                onChange={(e) => setЗапрос(e.target.value)}
                onKeyDown={поКлавише}
                placeholder={t('settings.providers.search')}
                aria-label={t('settings.providers.search')}
                className="min-w-0 flex-1 bg-transparent py-1 font-mono text-sm text-ink outline-none placeholder:font-sans placeholder:text-muted"
              />
            </div>

            <ul ref={списокРеф} className="max-h-[16rem] overflow-y-auto py-1" role="listbox">
              {пункты.map((пункт, i) => (
                <li key={пункт.key}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={пункт.model === value}
                    onMouseEnter={() => setАктивный(i)}
                    onClick={() => выбрать(пункт.model)}
                    className={cn(
                      'flex w-full items-center gap-s2 rounded-sm px-2 py-1.5 text-left text-sm',
                      i === активный ? 'bg-surface-2 text-ink-strong' : 'text-ink',
                    )}
                  >
                    <Icon
                      name="check"
                      size={14}
                      className={cn('shrink-0', пункт.model === value ? 'text-ok' : 'opacity-0')}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      <span className={пункт.model ? 'font-mono' : ''}>{пункт.title}</span>
                      {пункт.note ? (
                        <span className="ml-s2 font-mono text-xs text-muted">{пункт.note}</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              ))}
              {пункты.length === 0 && (
                <li className="px-2 py-3 text-center text-sm text-muted">
                  {t('settings.providers.nothing')}
                </li>
              )}
            </ul>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  )
}
