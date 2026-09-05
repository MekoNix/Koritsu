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

const email = z
  .string()
  .min(1, { message: t('auth.valid.emailRequired') })
  .max(320)
  .email({ message: t('auth.valid.emailFormat') })

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

export const registerSchema = z.object({ email, password: newPassword })

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
