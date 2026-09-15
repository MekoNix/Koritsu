/**
 * SourcePicker — откуда взять набор: файл или вставленный текст.
 *
 * Выбранный файл проверяется сразу, без второго нажатия: человек выбрал файл, чтобы
 * узнать, годится ли он. Вставленный текст — по кнопке «Проверить»: текст набирают и
 * правят, и проверка на каждую букву была бы шумом.
 *
 * Принимаются `.json` набора и таблицы `.csv`/`.tsv`. Файл читается в браузере
 * (`File.text()`) и уезжает текстом; потолок 5 МБ проверяется здесь же, до отправки.
 * Файл, который не читается как UTF-8, отклоняется сразу — иначе проверка службы
 * показала бы вместо проблем кракозябры. Markdown-файл (`.md`) набором больше не
 * является — об этом сказано сразу, без запроса к службе.
 *
 * На компьютере файл можно перетащить в поле. На телефоне у поля выбора нет фильтра
 * расширений: системный выбор файла на Android прячет файлы, тип которых ему не
 * известен (`.tsv`, иногда `.json`), а проверка всё равно скажет, если файл не тот.
 */
import { useRef, useState, type DragEvent } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon, Textarea } from '@/ui'

import { CARDS_FILE_MAX_BYTES, type CardsSource } from '../api'
import { useIsPhone } from '../hooks/useIsPhone'

type Режим = 'file' | 'text'
type Формат = 'json' | 'csv' | 'tsv'

const ФОРМАТЫ: readonly Формат[] = ['json', 'csv', 'tsv']
const ПРИНИМАЕТ = '.json,.csv,.tsv,application/json,text/csv,text/tab-separated-values'

function расширение(name: string | undefined): string {
  const части = (name ?? '').toLowerCase().split('.')
  return части.length > 1 ? (части.pop() ?? '') : ''
}

function форматИмени(name: string | undefined): Формат {
  const ext = расширение(name)
  return ext === 'csv' ? 'csv' : ext === 'tsv' ? 'tsv' : 'json'
}

export type SourcePickerProps = {
  onSource: (source: CardsSource) => void
  /** Идёт проверка — кнопки показывают ожидание. */
  busy?: boolean
  /** Текст, с которым открыть поле вставки (пример набора). */
  initialText?: string
  initialFilename?: string
  className?: string
}

export function SourcePicker({ onSource, busy = false, initialText, initialFilename, className }: SourcePickerProps) {
  const t = useT()
  const isPhone = useIsPhone()
  const [режим, setРежим] = useState<Режим>(initialText ? 'text' : 'file')
  const [текст, setТекст] = useState(initialText ?? '')
  const [формат, setФормат] = useState<Формат>(форматИмени(initialFilename))
  const [файл, setФайл] = useState<string | null>(null)
  const [беда, setБеда] = useState<string | null>(null)
  const [над, setНад] = useState(false)
  const поле = useRef<HTMLInputElement>(null)

  async function прочитать(f: File) {
    setБеда(null)
    const ext = расширение(f.name)
    if (ext === 'md' || ext === 'markdown') {
      setБеда(t('cards.upload.mdRefused'))
      return
    }
    if (f.size > CARDS_FILE_MAX_BYTES) {
      setБеда(t('cards.common.fileTooBig'))
      return
    }
    let тело: string
    try {
      тело = await f.text()
    } catch {
      setБеда(t('cards.common.fileUnreadable'))
      return
    }
    if (тело.includes('\uFFFD')) {
      setБеда(t('cards.common.fileUnreadable'))
      return
    }
    setФайл(f.name)
    onSource({ text: тело.replace(/^\uFEFF/, ''), filename: f.name })
  }

  function проверитьТекст() {
    setБеда(null)
    if (!текст.trim()) {
      setБеда(t('cards.upload.textEmpty'))
      return
    }
    if (new Blob([текст]).size > CARDS_FILE_MAX_BYTES) {
      setБеда(t('cards.common.fileTooBig'))
      return
    }
    const имя = initialFilename && форматИмени(initialFilename) === формат ? initialFilename : `text.${формат}`
    onSource({ text: текст, filename: имя })
  }

  function наБросок(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setНад(false)
    const f = e.dataTransfer.files[0]
    if (f) void прочитать(f)
  }

  const вкладка = (value: Режим, label: string, icon: 'upload' | 'edit') => (
    <button
      type="button"
      role="radio"
      aria-checked={режим === value}
      onClick={() => {
        setРежим(value)
        setБеда(null)
      }}
      className={cn(
        'inline-flex min-h-[44px] items-center justify-center gap-s2 rounded-[calc(var(--btn-radius)-2px)] px-s3 text-sm font-medium min-[641px]:min-h-[34px]',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        режим === value ? 'bg-surface text-ink-strong shadow-1' : 'text-muted hover:text-ink',
      )}
    >
      <Icon name={icon} size={16} />
      {label}
    </button>
  )

  return (
    <div className={cn('flex min-w-0 flex-col gap-s3', className)}>
      <div
        role="radiogroup"
        aria-label={t('cards.upload.mode')}
        className="grid grid-cols-2 gap-0.5 rounded-btn border border-line bg-surface-2 p-[3px] min-[641px]:inline-grid min-[641px]:self-start"
      >
        {вкладка('file', t('cards.upload.modeFile'), 'upload')}
        {вкладка('text', t('cards.upload.modeText'), 'edit')}
      </div>

      {режим === 'file' ? (
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setНад(true)
          }}
          onDragLeave={() => setНад(false)}
          onDrop={наБросок}
          className={cn(
            'flex flex-col items-center justify-center gap-s3 rounded-md border-2 border-dashed px-s4 py-s6 text-center',
            над ? 'border-accent bg-accent-bg' : 'border-line-strong bg-surface',
          )}
        >
          <Icon name="upload" size={28} className="text-muted" />
          <p className="m-0 max-w-[40ch] text-sm text-muted">{isPhone ? t('cards.upload.dropPhone') : t('cards.upload.drop')}</p>
          {файл && <p className="m-0 break-all font-mono text-sm text-ink-strong">{файл}</p>}
          <Button
            variant={файл ? 'secondary' : 'primary'}
            size={isPhone ? 'lg' : 'md'}
            loading={busy}
            onClick={() => поле.current?.click()}
            className="max-[640px]:w-full"
          >
            <Icon name="file" size={16} />
            {файл ? t('cards.upload.change') : t('cards.upload.pick')}
          </Button>
          <input
            ref={поле}
            type="file"
            accept={isPhone ? undefined : ПРИНИМАЕТ}
            className="sr-only"
            tabIndex={-1}
            aria-hidden="true"
            onChange={(e) => {
              const f = e.target.files?.[0]
              e.target.value = ''
              if (f) void прочитать(f)
            }}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-s3">
          <Textarea
            label={t('cards.upload.text')}
            value={текст}
            rows={isPhone ? 10 : 14}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            placeholder={t(формат === 'json' ? 'cards.upload.textPlaceholder' : 'cards.upload.textPlaceholderTable')}
            className="font-mono text-[13px] leading-snug"
            onChange={(e) => setТекст(e.target.value)}
          />
          <div className="flex flex-wrap items-center gap-s3">
            <div role="radiogroup" aria-label={t('cards.upload.format')} className="inline-flex gap-0.5 rounded-btn border border-line bg-surface-2 p-[3px]">
              {ФОРМАТЫ.map((f) => (
                <button
                  key={f}
                  type="button"
                  role="radio"
                  aria-checked={формат === f}
                  onClick={() => setФормат(f)}
                  className={cn(
                    'inline-flex min-h-[40px] min-w-[56px] items-center justify-center rounded-[calc(var(--btn-radius)-2px)] px-s3 text-sm font-medium min-[641px]:min-h-[30px]',
                    формат === f ? 'bg-surface text-ink-strong shadow-1' : 'text-muted hover:text-ink',
                  )}
                >
                  {t(`cards.upload.formats.${f}`)}
                </button>
              ))}
            </div>
            <Button variant="primary" size={isPhone ? 'lg' : 'md'} loading={busy} onClick={проверитьТекст} className="max-[640px]:w-full">
              <Icon name="check" size={16} />
              {t('cards.upload.check')}
            </Button>
          </div>
        </div>
      )}

      {беда && (
        <p role="alert" className="m-0 text-sm text-err">
          {беда}
        </p>
      )}
    </div>
  )
}
