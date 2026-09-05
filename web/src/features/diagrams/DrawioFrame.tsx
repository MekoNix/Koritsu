/**
 * DrawioFrame — встроенный редактор draw.io с нашей схемой внутри.
 *
 * Кадр живёт на чужом домене (`embed.diagrams.net`), поэтому у него две беды,
 * которых не бывает у своих компонентов, и обе разобраны здесь:
 *
 * 1. **Он может не подняться вовсе.** Сети нет, домен закрыт, расширение
 *    браузера вырезало кадр — событий `message` при этом не будет никаких, и
 *    отличить «грузится» от «не загрузится» можно только временем. Поэтому
 *    ждём `ПОДЪЁМ_МС` и, не дождавшись, показываем состояние «предпросмотр
 *    недоступен»: XML при этом цел и его можно скачать. Экран не ломается —
 *    это требование задания, а не вежливость.
 * 2. **Он говорит только сообщениями.** Показать XML — `postMessage`, а не
 *    свойство. Пока кадр не сказал `init`, слать ему нечего: сообщение,
 *    отправленное раньше, теряется молча. Поэтому последний XML держится
 *    ссылкой и уезжает в кадр в тот момент, когда тот отзовётся.
 *
 * Правки человека возвращаются событием `autosave` и уезжают наверх
 * (`onEdited`): «скачать XML» обязано скачивать то, что человек видит, а не то,
 * что построила служба десять правок назад.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { useAppearance } from '@/theme'
import { Button, EmptyState, Icon, Spinner } from '@/ui'

import { EMBED_ORIGIN, EMPTY_XML, embedUrl, loadMessage, parseEmbedEvent } from './drawio'

/** Сколько ждём слова от кадра, прежде чем счесть его недоступным. */
const ПОДЪЁМ_МС = 12_000

export type FrameState = 'connecting' | 'ready' | 'unavailable'

export type DrawioFrameProps = {
  /** XML схемы; `null` — показать пустой холст (схемы ещё нет). */
  xml: string | null
  /** Человек поправил схему руками. */
  onEdited?: (xml: string) => void
  /** Состояние кадра наружу: по нему шапка предпросмотра пишет, что происходит. */
  onStateChange?: (state: FrameState) => void
  className?: string
}

export function DrawioFrame({ xml, onEdited, onStateChange, className }: DrawioFrameProps) {
  const t = useT()
  const { appearance } = useAppearance()
  const кадр = useRef<HTMLIFrameElement | null>(null)
  const последний = useRef<string | null>(xml)
  const готов = useRef(false)
  const [state, setState] = useState<FrameState>('connecting')
  // Попытка: смена числа перезагружает кадр целиком — другого способа поднять
  // упавший `iframe` нет, у него нет ни `reload()`, ни события «попробуй ещё».
  const [попытка, setПопытка] = useState(0)
  const наПравку = useRef(onEdited)
  наПравку.current = onEdited

  последний.current = xml

  const сменить = useCallback(
    (значение: FrameState) => {
      setState(значение)
      onStateChange?.(значение)
    },
    [onStateChange],
  )

  // Слушаем кадр. Пересобирается на каждую попытку: у новой попытки новое окно.
  useEffect(() => {
    готов.current = false
    сменить('connecting')

    function слушать(событие: MessageEvent) {
      if (событие.origin !== EMBED_ORIGIN) return
      if (кадр.current && событие.source !== кадр.current.contentWindow) return
      const весть = parseEmbedEvent(событие.data)
      if (!весть) return
      if (весть.event === 'init') {
        готов.current = true
        сменить('ready')
        кадр.current?.contentWindow?.postMessage(
          loadMessage(последний.current ?? EMPTY_XML),
          EMBED_ORIGIN,
        )
        return
      }
      if ((весть.event === 'autosave' || весть.event === 'save') && весть.xml) {
        наПравку.current?.(весть.xml)
      }
    }

    window.addEventListener('message', слушать)
    const срок = window.setTimeout(() => {
      if (!готов.current) сменить('unavailable')
    }, ПОДЪЁМ_МС)
    return () => {
      window.removeEventListener('message', слушать)
      window.clearTimeout(срок)
    }
  }, [попытка, сменить])

  // Новая схема — показать её, но только если кадру уже есть что слушать.
  useEffect(() => {
    if (!готов.current) return
    кадр.current?.contentWindow?.postMessage(loadMessage(xml ?? EMPTY_XML), EMBED_ORIGIN)
  }, [xml])

  if (state === 'unavailable') {
    return (
      <div className={className}>
        <EmptyState
          icon="warning"
          title={t('diagrams.preview.offline')}
          text={t('diagrams.preview.offlineText')}
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setПопытка((n) => n + 1)
              }}
            >
              <Icon name="refresh" size={16} />
              {t('diagrams.preview.retry')}
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className={cn('relative', className)}>
      <iframe
        key={попытка}
        ref={кадр}
        title={t('diagrams.preview.title')}
        src={embedUrl({ dark: appearance.mode === 'dark' })}
        className="h-full w-full border-0 bg-surface"
        // `sandbox` здесь намеренно нет. Кадр и так на чужом домене, то есть до
        // нашей cookie и нашего DOM не достаёт по самому правилу происхождения;
        // а `sandbox` без `allow-same-origin` делает происхождение кадра
        // «null» — и тогда ломается ровно то, ради чего он тут стоит:
        // `postMessage` с адресом получателя и проверка `event.origin`.
        referrerPolicy="no-referrer"
      />
      {state === 'connecting' && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center gap-s2 text-sm text-muted">
          <Spinner size={18} />
          {t('diagrams.work.building')}
        </div>
      )}
    </div>
  )
}
