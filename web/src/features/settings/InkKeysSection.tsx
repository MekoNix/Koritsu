/**
 * InkKeysSection — «Распознавание рукописи (MyScript)».
 *
 * **Ключа здесь не один, а пара, и это единица настройки.** MyScript подписывает
 * каждое соединение HMAC-ом, в котором участвуют оба ключа: `applicationKey`
 * едет в адресе сокета, `hmacKey` подписывает и наружу не уезжает никогда. Один
 * без другого не распознаёт ничего, поэтому форма спрашивает оба поля, кнопка
 * одна, служба кладёт обе строки одним запросом (`PUT /api/keys/ink`), а
 * отзыв убирает пару целиком. Заведённая половина — это не «настроено
 * наполовину», а «не настроено», и показывать её как ключ значило бы обещать
 * работающую доску там, где сокет закроется отказом.
 *
 * **В выборе модели этих ключей нет.** Они из той же таблицы, что ключи
 * поставщиков моделей, но платят за другое: ключ модели — за прогон, ключ
 * MyScript — за открытие доски, и пресета у него не существует вовсе. Прогон с
 * таким поставщиком служба отвергает `400 unknown_provider`, поэтому в списках
 * агента их нет (`types.modelProviders`), а живут они своим подразделом.
 *
 * **Ключи лежат на сервере и наружу не возвращаются.** Наружу — поставщик,
 * четыре последних знака и даты. Иначе и нельзя: подпись считает мост службы, а
 * браузер получает заглушки.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Card, Chip, Dialog, Icon, Input, SkeletonLines, useToast } from '@/ui'

import { useKeyProviders, useModelKeys, useRevokeInkKeys, useSetInkKeys } from './api'
import { formatDate } from './format'
import { isInkProvider, INK_PROVIDER_APP, INK_PROVIDER_HMAC } from './types'

/** Кабинет, где ключи выдают. Адрес чужой и в словарь не уезжает. */
const КАБИНЕТ = 'https://developer.myscript.com/getting-started/web'

export function InkKeysSection() {
  const t = useT()
  const toast = useToast()
  const список = useModelKeys()
  const поставщики = useKeyProviders()
  const записать = useSetInkKeys()
  const отозвать = useRevokeInkKeys()

  const [app, setApp] = useState('')
  const [hmac, setHmac] = useState('')
  const [беда, setБеда] = useState<string | null>(null)
  const [отзываем, setОтзываем] = useState(false)

  const свои = (список.data ?? []).filter(
    (ключ) => isInkProvider(поставщики.data, ключ.provider) && !ключ.revoked_at,
  )
  const приложение = свои.find((ключ) => ключ.provider === INK_PROVIDER_APP)
  const подпись = свои.find((ключ) => ключ.provider === INK_PROVIDER_HMAC)
  // Настроено — только когда есть оба. Половина пары показывается как «не
  // настроено» с пометкой, потому что доска с ней всё равно не работает.
  const пара = !!приложение && !!подпись
  const половина = свои.length === 1

  async function сохранить() {
    setБеда(null)
    try {
      await записать.mutateAsync({ application_key: app.trim(), hmac_key: hmac.trim() })
      setApp('')
      setHmac('')
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <>
      <Card
        title={t('settings.ink.title')}
        desc={t('settings.ink.text')}
        action={
          <Chip tone={пара ? 'ok' : половина ? 'warn' : 'muted'}>
            {t(пара ? 'settings.ink.on' : половина ? 'settings.ink.half' : 'settings.ink.off')}
          </Chip>
        }
      >
        {список.isLoading && <SkeletonLines count={2} />}

        {свои.length > 0 && (
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
              </li>
            ))}
            <li>
              <Button variant="ghost" size="sm" onClick={() => setОтзываем(true)}>
                <Icon name="trash" size={16} />
                {t('settings.ink.revokePair')}
              </Button>
            </li>
          </ul>
        )}

        <div className="flex flex-col gap-s3">
          <Input
            label={t('settings.ink.app')}
            hint={t('settings.ink.appHint')}
            type="password"
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            value={app}
            onChange={(e) => setApp(e.target.value)}
          />
          <Input
            label={t('settings.ink.hmac')}
            hint={t('settings.ink.hmacHint')}
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
            loading={записать.isPending}
            // Обе строки или ничего: кнопка, живая при одном заполненном поле,
            // предлагала бы завести половину пары.
            disabled={app.trim().length < 8 || hmac.trim().length < 8}
            onClick={() => void сохранить()}
          >
            <Icon name="plus" size={16} />
            {t('settings.ink.save')}
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
        open={отзываем}
        onOpenChange={setОтзываем}
        title={t('settings.ink.revokePair')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setОтзываем(false)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={отозвать.isPending}
              onClick={() =>
                отозвать.mutate(undefined, {
                  onSuccess: () => setОтзываем(false),
                  onError: (е) => toast.fail(е),
                })
              }
            >
              {t('settings.keys.revoke')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">{t('settings.ink.revokeText')}</p>
      </Dialog>
    </>
  )
}
