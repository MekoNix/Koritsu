/**
 * HotkeysSection — «Горячие клавиши» (`/settings/hotkeys`).
 *
 * Список берётся из `lib/hotkeys.HOTKEY_ACTIONS` — того же места, по которому
 * клавиши и работают. Свой список здесь разошёлся бы с настоящим молча, и
 * человек менял бы сочетание, которое ничего не делает.
 *
 * **Смена — записью нажатия, а не набором текста.** Поле «Ctrl+Shift+K» словами
 * пришлось бы разбирать, и разобрано оно было бы неверно на первой же русской
 * раскладке. Здесь человек жмёт кнопку и нажимает сочетание; ловится оно на
 * `keydown` в диалоге, и одни модификаторы (пока `Ctrl` держат, а вторую
 * клавишу выбирают) сочетанием не считаются.
 *
 * **Переназначения живут в браузере** (`localStorage`), а не в профиле:
 * клавиатура — свойство машины, а не человека, и та же настройка на чужом
 * ноутбуке была бы скорее помехой.
 *
 * `Ctrl+Enter` и `Esc` показаны, но не меняются: первый обрабатывает само поле
 * ввода, второй — Radix у окна. Обещать их переназначение значило бы обещать
 * то, что не сработает; поэтому вместо кнопки у них стоит пометка.
 */
import { useEffect, useState } from 'react'

import { useT } from '@/i18n'
import {
  HOTKEY_ACTIONS,
  comboFromEvent,
  hotkeyLabel,
  resetHotkeys,
  setHotkey,
  useHotkeyBindings,
} from '@/lib/hotkeys'
import { Button, Card, Dialog, Icon } from '@/ui'

export function HotkeysSection() {
  const t = useT()
  const сочетания = useHotkeyBindings()
  /** Какое действие сейчас переназначают. `null` — окно закрыто. */
  const [пишем, setПишем] = useState<string | null>(null)
  const [поймано, setПоймано] = useState<string | null>(null)

  // Слушатель живёт, только пока открыто окно записи: постоянный отбирал бы у
  // сайта все сочетания разом.
  useEffect(() => {
    if (!пишем) return
    const слушать = (event: KeyboardEvent) => {
      // Отменяем действие браузера у любого нажатия, пока идёт запись: иначе
      // Ctrl+S посреди записи открыл бы окно сохранения страницы.
      event.preventDefault()
      const combo = comboFromEvent(event)
      if (combo) setПоймано(combo)
    }
    window.addEventListener('keydown', слушать)
    return () => window.removeEventListener('keydown', слушать)
  }, [пишем])

  const открыть = (id: string) => {
    setПоймано(null)
    setПишем(id)
  }

  const закрыть = () => {
    setПишем(null)
    setПоймано(null)
  }

  const сохранить = () => {
    if (пишем && поймано) setHotkey(пишем, поймано)
    закрыть()
  }

  return (
    <>
      <Card
        title={t('settings.hotkeys.title')}
        desc={t('settings.hotkeys.text')}
        action={
          <Button variant="secondary" size="sm" onClick={() => resetHotkeys()}>
            {t('settings.hotkeys.resetAll')}
          </Button>
        }
      >
        <ul className="flex flex-col gap-s2">
          {HOTKEY_ACTIONS.map((действие) => {
            const текущее = сочетания[действие.id] ?? действие.default
            const изменено = !действие.fixed && текущее !== действие.default
            return (
              <li
                key={действие.id}
                className="flex flex-wrap items-center gap-s3 rounded-sm border border-line bg-surface-2 px-s3 py-s2"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink-strong">
                    {t(`settings.hotkeys.action.${действие.id}`)}
                  </span>
                  <span className="block text-xs text-muted">
                    {t(`settings.hotkeys.where.${действие.id}`)}
                  </span>
                </span>

                <kbd className="rounded-sm border border-line-strong bg-surface px-2 py-1 font-mono text-xs text-ink">
                  {hotkeyLabel(текущее)}
                </kbd>

                {действие.fixed ? (
                  <span className="text-xs text-muted">{t('settings.hotkeys.fixed')}</span>
                ) : (
                  <>
                    <Button variant="ghost" size="sm" onClick={() => открыть(действие.id)}>
                      <Icon name="edit" size={16} />
                      {t('settings.hotkeys.change')}
                    </Button>
                    {изменено && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setHotkey(действие.id, null)}
                        aria-label={`${t('settings.hotkeys.reset')} ${t(`settings.hotkeys.action.${действие.id}`)}`}
                      >
                        {t('settings.hotkeys.reset')}
                      </Button>
                    )}
                  </>
                )}
              </li>
            )
          })}
        </ul>

        <p className="text-xs text-muted">{t('settings.hotkeys.storageHint')}</p>
      </Card>

      <Dialog
        open={пишем !== null}
        onOpenChange={(open) => !open && закрыть()}
        title={t('settings.hotkeys.recordTitle')}
        description={t('settings.hotkeys.recordHint')}
        footer={
          <>
            <Button variant="ghost" onClick={закрыть}>
              {t('common.action.cancel')}
            </Button>
            <Button variant="primary" disabled={!поймано} onClick={сохранить}>
              {t('common.action.save')}
            </Button>
          </>
        }
      >
        <div
          role="status"
          className="flex min-h-[64px] items-center justify-center rounded-md border border-dashed border-line-strong bg-surface-2"
        >
          <kbd className="font-mono text-md text-ink-strong">
            {поймано ? hotkeyLabel(поймано) : t('settings.hotkeys.waiting')}
          </kbd>
        </div>
      </Dialog>
    </>
  )
}
