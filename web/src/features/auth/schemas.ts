/**
 * Схемы форм входа и регистрации.
 *
 * zod, а не проверки руками, по одной причине: описание «какие поля и какой
 * формы» здесь ОДНО и работает дважды — им проверяется ввод и из него же
 * выводится тип значений формы. Две проверки (в браузере и в службе) остаются,
 * и это правильно: браузерная нужна для скорости ответа, серверная — потому
 * что браузеру верить нельзя.
 *
 * Границы взяты из службы (`packages/api/accounts/routes.py`, схемы `RegisterIn`,
 * `ResetIn`): пароль — не короче 10 знаков, почта — не длиннее 320. Расхождение
 * означало бы, что форма пропускает то, что служба отвергает.
 */
import { z } from 'zod'

import { t } from '@/i18n'

/**
 * Почта: та же проверка, что в службе (`accounts/service.py: EMAIL_RE`), а не
 * `z.string().email()`.
 *
 * `z.email()` требует латиницы в домене и отказывает `admin@пример.рф`, тогда
 * как служба такой адрес принимает и заводит по нему аккаунт. Расхождение в эту
 * сторону хуже обратного: форма не пускает туда, куда служба пускает, и человек
 * с доменом на кириллице (или на любом другом алфавите) не заводит аккаунт
 * вовсе — при том, что настоящая проверка адреса одна, и она в том, дошло ли
 * письмо.
 *
 * Поэтому здесь дословный перенос выражения службы: до `@` — что угодно, кроме
 * пробела и второй собаки, не длиннее 64 знаков; после — хотя бы одна точка,
 * и куски между точками непустые.
 */
const EMAIL_RE = /^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$/u

const email = z
  .string()
  .trim()
  .min(1, { message: t('auth.valid.emailRequired') })
  .max(320)
  .regex(EMAIL_RE, { message: t('auth.valid.emailFormat') })

/**
 * Ник: буквы, цифры, `_` и `-`, от 2 до 32 знаков
 * (`accounts/service.py: NICK_RE`, `годный_ник`).
 *
 * `\p{L}` и `\p{N}` с флагом `u`, а не `[a-zA-Z0-9]`: кириллица разрешена
 * намеренно, и список «латиница плюс кириллица» отказал бы человеку с
 * любым третьим алфавитом ни за что. Это же и делает `\w` в Python на стороне
 * службы — но `\w` в JavaScript означает ровно ASCII, поэтому здесь он
 * записан длиннее.
 *
 * Три сообщения на три беды, а не одно на все: «ник короче двух знаков» и «в
 * нике только буквы и цифры» чинятся разными действиями.
 */
const nickname = z
  .string()
  .trim()
  .min(1, { message: t('auth.valid.nicknameRequired') })
  .min(2, { message: t('auth.valid.nicknameShort') })
  .max(32, { message: t('auth.valid.nicknameLong') })
  .regex(/^[\p{L}\p{N}_-]+$/u, { message: t('auth.valid.nicknameChars') })

const newPassword = z
  .string()
  .min(10, { message: t('auth.valid.passwordShort') })
  .max(1024)

export const loginSchema = z.object({
  email,
  // На входе длина не проверяется: старый пароль может быть короче нынешнего
  // предела, и человеку надо дать войти и сменить его. Так же рассуждает и
  // служба — см. докстроку `LoginIn`.
  password: z
    .string()
    .min(1, { message: t('auth.valid.passwordRequired') })
    .max(1024),
})

export const registerSchema = z.object({ email, nickname, password: newPassword })

export const forgotSchema = z.object({ email })

export const resetSchema = z
  .object({ password: newPassword, repeat: z.string() })
  .refine((v) => v.password === v.repeat, {
    message: t('auth.valid.passwordMismatch'),
    path: ['repeat'],
  })

export type LoginValues = z.infer<typeof loginSchema>
export type RegisterValues = z.infer<typeof registerSchema>
export type ForgotValues = z.infer<typeof forgotSchema>
export type ResetValues = z.infer<typeof resetSchema>
