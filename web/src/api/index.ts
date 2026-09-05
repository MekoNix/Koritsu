// Одна дверь в службу: `import { api, unwrap, ApiError } from '@/api'`.
export { api, unwrap, readCookie, setUnauthorizedHandler } from './client'
export { ApiError, isApiError, errorText, errorField, NETWORK, UNKNOWN } from './errors'
export { keys } from './queryKeys'
export { useSseStream, type SseFrame, type SseState, type SseStatus } from './sse'
export * from './types'
