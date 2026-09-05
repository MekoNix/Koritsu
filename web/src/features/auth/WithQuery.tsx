/**
 * WithQuery — переход на другой путь с сохранённой строкой запроса.
 *
 * Нужен ровно для ссылок из писем: служба собирает их без приставки `auth`
 * (`{base_url}/confirm?token=…`, `{base_url}/reset?token=…` —
 * `packages/api/accounts/mail.py`), а страницы живут под `/auth/`. Обычный
 * `<Navigate to="/auth/reset" replace />` увёл бы человека на страницу сброса
 * **без токена**, то есть на «ссылка недействительна», — и выглядело бы это
 * как испорченное письмо.
 *
 * Отдельным файлом, а не рядом с `authRoutes`: в файле маршрутов кроме
 * компонентов лежит массив, и горячая перезагрузка Vite такой файл целиком
 * перезагружает (`react-refresh/only-export-components`).
 */
import { Navigate, useLocation } from 'react-router-dom'

export function WithQuery({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={`${to}${search}`} replace />
}
