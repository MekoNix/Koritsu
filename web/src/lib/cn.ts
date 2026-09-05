import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Склеить классы так, чтобы последний победил.
 *
 * Нужно ровно из-за одного: у компонента есть свои классы и есть `className`
 * снаружи. Без слияния `px-4` снаружи не перебивает `px-3` внутри — побеждает
 * тот, что стоит позже в CSS, а не тот, что написан позже в JSX.
 */
export function cn(...parts: ClassValue[]): string {
  return twMerge(clsx(parts))
}
