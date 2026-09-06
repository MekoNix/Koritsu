/**
 * ProfileSection — то, что служба знает о человеке, и то немногое, что он может
 * в себе поменять.
 *
 * Менять здесь можно ровно одно — **ник** (`PATCH /api/auth/me`). Ни имени, ни
 * фамилии, ни часового пояса у `users` нет; почту меняет администратор службы,
 * план — тоже. Поэтому раздел на две трети остался
 * читающим, и это честно: форма с полями, которые некуда отправить, хуже
 * отсутствия формы.
 *
 * **Почта показана частично** (`a***@mail.ru`, помощник `lib/maskEmail`), с
 * кнопкой «показать». Прячется она не от хозяина экрана — свой адрес он знает,
 * — а от тех, кто смотрит на экран вместе с ним: настройки открывают на
 * защите, на паре и в видеозвонке. Кнопка при этом обязана быть: почта нужна,
 * когда её диктуют или сверяют, и заставлять ради этого лезть в письма — это
 * прятка ради прятки.
 *
 * **Аватар — единственная картинка, которую человек может нам дать.** По
 * умолчанию он генеративный (решётка из идентификатора, `ui/Avatar.tsx`);
 * своя картинка загружается здесь — кнопкой или перетаскиванием, — и убирается
 * тут же. Подписи «откуда взялся аватар» на экране нет: человек видит своё
 * лицо или свою решётку и не спрашивал, как она посчитана.
 *
 * Файл выбирается и **сразу уезжает**: промежуточного «выбрано, нажмите
 * сохранить» нет, потому что решение здесь одно — вот эта картинка, — и
 * подтверждать его нечем. Пока запрос идёт, показывается выбранный файл
 * (`blob:`), а не прежний аватар: иначе нажатие выглядит как ничего не
 * сделавшее.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { errorField, errorText } from '@/api'
import { useMe, useUpdateProfile } from '@/api/hooks'
import { t as translate, useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { maskEmail } from '@/lib/maskEmail'
import {
  Avatar,
  Button,
  Card,
  Chip,
  ErrorState,
  Icon,
  Input,
  Row,
  SkeletonLines,
  useToast,
} from '@/ui'

import { useDeleteAvatar, useSetAvatar } from './api'
import { formatDate } from './format'

/**
 * Те же границы, что у службы (`accounts/service.py: NICK_RE`, `годный_ник`):
 * буквы, цифры, `_` и `-`, от 2 до 32 знаков. `\p{L}`/`\p{N}` вместо `\w` —
 * потому что `\w` в JavaScript означает ASCII, а кириллица разрешена.
 */
const schema = z.object({
  nickname: z
    .string()
    .trim()
    .min(2, { message: translate('settings.valid.nicknameShort') })
    .max(32, { message: translate('settings.valid.nicknameLong') })
    .regex(/^[\p{L}\p{N}_-]+$/u, { message: translate('settings.valid.nicknameChars') }),
})

type Values = z.infer<typeof schema>

/**
 * Что предлагает выбиралка файлов. Те же три типа, что принимает служба
 * (`accounts/avatar.py`), — и это подсказка, а не заслон: решают в службе
 * первые байты, а не расширение и не `accept`.
 */
const ТИПЫ = ['image/png', 'image/jpeg', 'image/webp'] as const

export function ProfileSection() {
  const t = useT()
  const toast = useToast()
  const me = useMe()
  const save = useUpdateProfile()
  const setAvatar = useSetAvatar()
  const dropAvatar = useDeleteAvatar()
  const [shown, setShown] = useState(false)
  const [dragging, setDragging] = useState(false)
  // Превью выбранного файла, пока он едет в службу. `blob:` живёт до
  // `revokeObjectURL`, поэтому адрес и хранится состоянием: без уборки каждая
  // проба картинки оставляла бы за собой файл в памяти вкладки.
  const [preview, setPreview] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview)
    },
    [preview],
  )

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    // `values`, а не `defaultValues`: профиль приезжает запросом, и поле,
    // заполненное один раз при первой отрисовке, осталось бы пустым.
    values: { nickname: me.data?.nickname ?? '' },
  })

  if (me.isLoading) {
    return (
      <Card title={t('settings.profile.title')}>
        <SkeletonLines count={5} />
      </Card>
    )
  }
  if (me.error) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />
  if (!me.data) return null

  const user = me.data

  async function загрузить(file: File | null | undefined) {
    if (!file) return
    const адрес = URL.createObjectURL(file)
    setPreview((прежний) => {
      if (прежний) URL.revokeObjectURL(прежний)
      return адрес
    })
    try {
      await setAvatar.mutateAsync(file)
    } catch (e) {
      toast.fail(e)
    } finally {
      // Превью снимается в любом случае: удачу показывает уже сам профиль
      // (версия выросла, адрес картинки другой), а неудачу — тост.
      setPreview((прежний) => {
        if (прежний) URL.revokeObjectURL(прежний)
        return null
      })
    }
  }

  async function убрать_аватар() {
    try {
      await dropAvatar.mutateAsync()
    } catch (e) {
      toast.fail(e)
    }
  }

  async function submit(values: Values) {
    try {
      await save.mutateAsync({ nickname: values.nickname })
    } catch (e) {
      // Отказ службы садится в поле, когда она назвала поле (`nickname_taken`
      // приходит с `where: body.nickname`); иначе — тостом.
      if (errorField(e) === 'nickname') {
        form.setError('nickname', { type: 'server', message: errorText(e) })
        return
      }
      toast.fail(e)
    }
  }

  return (
    <Card title={t('settings.profile.title')}>
      <div
        className={cn(
          'flex flex-wrap items-center gap-s4 rounded-md border border-dashed p-s3 transition-colors',
          dragging ? 'border-accent bg-accent-bg' : 'border-transparent',
        )}
        onDragOver={(event) => {
          // Без `preventDefault` браузер откроет брошенный файл вкладкой —
          // то есть уведёт человека с настроек в просмотр картинки.
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          void загрузить(event.dataTransfer.files[0])
        }}
      >
        <Avatar
          id={user.id}
          size={72}
          label={user.nickname}
          version={user.avatar_version}
          src={preview}
        />
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="break-all font-display text-lg font-semibold text-ink-strong">
            {user.nickname}
          </div>
          <div className="flex flex-wrap items-center gap-s2">
            <input
              ref={fileInput}
              type="file"
              className="sr-only-text"
              // Поле спрятано от глаз, но не от скринридера (`sr-only-text`), и
              // потому обязано называться: выбор файла остаётся в порядке
              // табуляции, а безымянное поле ввода читается как «файл».
              aria-label={t('settings.profile.avatarFile')}
              accept={ТИПЫ.join(',')}
              onChange={(event) => {
                void загрузить(event.target.files?.[0])
                // Поле чистится, иначе повторный выбор того же файла не даёт
                // события `change` и выглядит как «кнопка не работает».
                event.target.value = ''
              }}
            />
            <Button
              variant="ghost"
              size="sm"
              loading={setAvatar.isPending}
              onClick={() => fileInput.current?.click()}
            >
              <Icon name="upload" size={16} />
              {t('settings.profile.avatarUpload')}
            </Button>
            {user.avatar_version > 0 && (
              <Button
                variant="ghost"
                size="sm"
                loading={dropAvatar.isPending}
                onClick={() => void убрать_аватар()}
              >
                <Icon name="trash" size={16} />
                {t('settings.profile.avatarRemove')}
              </Button>
            )}
            <span className="text-xs text-muted">{t('settings.profile.avatarHint')}</span>
          </div>
          <div className="flex flex-wrap gap-s2">
            <Chip tone="accent">{user.plan}</Chip>
            <Chip tone={user.email_confirmed ? 'ok' : 'warn'}>
              {user.email_confirmed
                ? t('settings.profile.confirmed')
                : t('settings.profile.notConfirmed')}
            </Chip>
            <Chip tone={user.totp_enabled ? 'ok' : 'muted'}>
              {user.totp_enabled ? t('settings.profile.totpOn') : t('settings.profile.totpOff')}
            </Chip>
          </div>
        </div>
      </div>

      <form
        className="flex flex-wrap items-start gap-s3"
        noValidate
        onSubmit={form.handleSubmit(submit)}
      >
        <Input
          label={t('settings.profile.nickname')}
          hint={t('settings.profile.nicknameHint')}
          error={form.formState.errors.nickname?.message}
          wrapperClassName="w-[280px] max-w-full"
          {...form.register('nickname')}
        />
        <Button
          type="submit"
          variant="primary"
          className="mt-[26px]"
          loading={save.isPending}
          disabled={!form.formState.isDirty}
        >
          {t('settings.profile.save')}
        </Button>
      </form>

      <div className="flex flex-col">
        <Row label={t('settings.profile.email')}>
          {/* Показана частично, пока не попросили обратного. */}
          <span className="break-all">{shown ? user.email : maskEmail(user.email)}</span>
          <Button
            variant="ghost"
            size="sm"
            className="ml-s2 align-middle"
            onClick={() => setShown((было) => !было)}
          >
            <Icon name={shown ? 'eyeOff' : 'eye'} size={16} />
            {shown ? t('settings.profile.emailHide') : t('settings.profile.emailShow')}
          </Button>
        </Row>
        <Row label={t('settings.profile.plan')}>{user.plan}</Row>
        <Row label={t('settings.profile.id')}>
          <span className="break-all font-mono text-xs">{user.id}</span>
        </Row>
        <Row label={t('settings.profile.created')}>{formatDate(user.created_at)}</Row>
      </div>
    </Card>
  )
}
