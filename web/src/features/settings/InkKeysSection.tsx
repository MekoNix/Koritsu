/**
 * InkKeysSection — «Распознавание рукописи (MyScript)».
 *
 * Стоит в разделе «Конфигурация агентов», под ключами моделей, и это не
 * соседство по случайности: и там, и здесь человек заводит чужой ключ, которым
 * оплачивается чужая работа. Разными подразделами — потому что платят они за
 * разное: ключ модели за прогон, ключ MyScript за открытие доски.
 *
 * **Ключей два, и нужны оба.** MyScript подписывает каждое соединение HMAC-ом,
 * где ключом служит `applicationKey` вместе с `hmacKey`: один без другого не
 * работает вовсе. Поэтому форма спрашивает оба поля и отправляет их двумя
 * запросами подряд, а распознавание на доске включается, только когда заведены
 * оба.
 *
 * **Ключи живут на сервере и наружу не возвращаются.** Служба отдаёт поставщика,
 * четыре последних знака и даты — как у ключей моделей. Иначе и нельзя: держать
 * ключ в браузере и одновременно прятать его невозможно, потому что соединение
 * подписывает библиотека распознавания, и ключ ей нужен в памяти. Подпись
 * считает мост службы, а браузер получает заглушки.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Card, Chip, Dialog, Icon, Input, Row, SkeletonLines, useToast } from '@/ui'

import { useAddModelKey, useKeyProviders, useModelKeys, useRevokeModelKey } from './api'
import { formatDate } from './format'
import { isInkProvider, INK_PROVIDER_APP, INK_PROVIDER_HMAC, type ModelKey } from './types'

/** Кабинет, где ключи выдают. Адрес чужой и в словарь не уезжает. */
const КАБИНЕТ = 'https://developer.myscript.com/getting-started/web'

export function InkKeysSection() {
  const t = useT()
  const toast = useToast()
  const список = useModelKeys()
  const поставщики = useKeyProviders()
  const завести = useAddModelKey()
  const отозвать = useRevokeModelKey()

  const [app, setApp] = useState('')
  const [hmac, setHmac] = useState('')
  const [беда, setБеда] = useState<string | null>(null)
  const [отзываем, setОтзываем] = useState<ModelKey | null>(null)

  const свои = (список.data ?? []).filter(
    (ключ) => isInkProvider(поставщики.data, ключ.provider) && !ключ.revoked_at,
  )

  async function записать() {
    setБеда(null)
    try {
      // По очереди, а не разом: служба заводит по ключу за запрос, и второй
      // обязан не уехать, если первый не принят, — иначе останется половина
      // пары, с которой распознавание всё равно не работает.
      if (app.trim()) await завести.mutateAsync({ provider: INK_PROVIDER_APP, key: app.trim() })
      if (hmac.trim()) await завести.mutateAsync({ provider: INK_PROVIDER_HMAC, key: hmac.trim() })
      setApp('')
      setHmac('')
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <>
      <Card title={t('settings.ink.title')} desc={t('settings.ink.text')}>
        {список.isLoading && <SkeletonLines count={2} />}

        {список.data && свои.length > 0 && (
          <ul className="flex flex-col gap-s2">
            {свои.map((ключ) => (
              <li
                key={ключ.id}
                className="flex flex-wrap items-center gap-s3 rounded-sm border border-line bg-surface-2 px-s3 py-s2"
              >
                <Icon name="key" size={18} className="text-muted" />
                <span className="font-semibold text-ink-strong">
                  {t(`settings.ink.provider.${ключ.provider}`)}
                </span>
                <span className="font-mono text-sm text-muted">…{ключ.last4}</span>
                <span className="ml-auto text-xs text-muted">
                  {t('settings.keys.created')}: {formatDate(ключ.created_at)}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setОтзываем(ключ)}
                  aria-label={`${t('settings.keys.revoke')} ${ключ.provider}`}
                >
                  <Icon name="trash" size={16} />
                  {t('settings.keys.revoke')}
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-s3">
          <Input
            label={t('settings.ink.app')}
            type="password"
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            value={app}
            onChange={(e) => setApp(e.target.value)}
          />
          <Input
            label={t('settings.ink.hmac')}
            type="password"
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            value={hmac}
            onChange={(e) => setHmac(e.target.value)}
          />
          <Button
            variant="primary"
            className="self-start"
            loading={завести.isPending}
            disabled={!app.trim() && !hmac.trim()}
            onClick={() => void записать()}
          >
            <Icon name="plus" size={16} />
            {t('settings.keys.add')}
          </Button>
          {беда && <p className="text-sm text-err">{беда}</p>}
        </div>

        <p className="text-xs text-muted">
          <a href={КАБИНЕТ} target="_blank" rel="noreferrer noopener" className="underline">
            {t('settings.ink.cabinet')}
          </a>{' '}
          · {t('settings.ink.quota')}
        </p>
      </Card>

      <Dialog
        open={отзываем !== null}
        onOpenChange={(открыто) => !открыто && setОтзываем(null)}
        title={t('settings.keys.revokeTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setОтзываем(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={отозвать.isPending}
              onClick={() => {
                if (!отзываем) return
                отозвать.mutate(отзываем.id, {
                  onSuccess: () => setОтзываем(null),
                  onError: (е) => toast.fail(е),
                })
              }}
            >
              {t('settings.keys.revoke')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">{t('settings.ink.revokeText')}</p>
        {отзываем && (
          <div className="mt-s3">
            <Row label={t('settings.keys.last4')}>
              <Chip tone="muted">…{отзываем.last4}</Chip>
            </Row>
          </div>
        )}
      </Dialog>
    </>
  )
}
