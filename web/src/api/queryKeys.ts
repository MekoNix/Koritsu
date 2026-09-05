/**
 * queryKeys — ключи кэша TanStack Query в одном месте.
 *
 * Ключ — это адрес строки в кэше, и он же адрес для сброса
 * (`queryClient.invalidateQueries`). Разъехавшиеся ключи не ломают сборку: они
 * просто перестают сбрасывать друг друга, и человек видит устаревшие данные
 * без единой ошибки в консоли. Поэтому ключи не пишутся в вызовах руками.
 *
 * Соглашение: первый элемент — область (`'me'`, `'projects'`, …), дальше —
 * уточнения от общего к частному, чтобы `invalidateQueries({ queryKey: ['projects'] })`
 * гасил и список, и каждый проект.
 *
 * Агентам B–E: заводите свои ключи здесь же, отдельным полем; файл дописывается,
 * а не переписывается.
 */

export const keys = {
  me: ['me'] as const,
  modules: ['modules'] as const,
  usage: ['usage'] as const,
  notifications: ['notifications'] as const,
  jobs: {
    all: ['jobs'] as const,
    list: (status?: string) => ['jobs', 'list', status ?? 'all'] as const,
    one: (id: string) => ['jobs', 'one', id] as const,
  },
  // Область B: пространства, проекты и материалы.
  workspaces: {
    all: ['workspaces'] as const,
    personal: ['workspaces', 'personal'] as const,
  },
  projects: {
    all: ['projects'] as const,
    /** Список проектов пространства; корзина — отдельный список, не фильтр кэша. */
    list: (workspaceId: string, trash: boolean) =>
      ['projects', 'list', workspaceId, trash ? 'trash' : 'active'] as const,
    one: (id: string) => ['projects', 'one', id] as const,
    materials: (id: string) => ['projects', 'materials', id] as const,
    pending: (id: string) => ['projects', 'pending', id] as const,
    materialText: (projectId: string, materialId: string) =>
      ['projects', 'material-text', projectId, materialId] as const,
  },
  // Область C: отчёты. Ключи начинаются с `projects`, а не со своего корня,
  // намеренно: теги и значения принадлежат проекту, и сброс проекта
  // (`invalidateQueries({ queryKey: keys.projects.one(id) })`) обязан гасить их
  // заодно — иначе после переименования или смены шаблона экран работы покажет
  // прежний список тегов и не заметит этого.
  reports: {
    tags: (projectId: string) => ['projects', 'one', projectId, 'tags'] as const,
    values: (projectId: string) => ['projects', 'one', projectId, 'values'] as const,
    versions: (projectId: string, key: string) =>
      ['projects', 'one', projectId, 'versions', key] as const,
    version: (projectId: string, key: string, n: number) =>
      ['projects', 'one', projectId, 'versions', key, n] as const,
  },
  // Область E: настройки аккаунта.
  modelKeys: ['model-keys'] as const,
  keyProviders: ['key-providers'] as const,
  apiTokens: ['api-tokens'] as const,
  // Область E: админка. Всё под одним корнем, чтобы правка человека гасила и
  // список, и его карточку одним `invalidateQueries({ queryKey: ['admin'] })`.
  admin: {
    all: ['admin'] as const,
    users: (limit: number) => ['admin', 'users', limit] as const,
    queue: ['admin', 'queue'] as const,
    security: (kind: string | null, limit: number) =>
      ['admin', 'security', kind ?? 'all', limit] as const,
  },
  // Область D: схемы. Ключи свои, а не чужие `projects.*`, намеренно: под теми
  // лежат формы области B, и гасить их своим списком схем значило бы сбрасывать
  // чужой кэш ради своего.
  diagrams: {
    all: ['diagrams'] as const,
    modes: ['diagrams', 'modes'] as const,
    themes: ['diagrams', 'themes'] as const,
    /** Проекты всех пространств человека — из них собирается список схем. */
    projects: ['diagrams', 'projects'] as const,
    /** Значения одного проекта: из них отбираются теги со схемами. */
    values: (projectId: string) => ['diagrams', 'values', projectId] as const,
    /** Содержимое артефакта схемы — тот самый XML draw.io. */
    artifact: (projectId: string, artifactId: string) =>
      ['diagrams', 'artifact', projectId, artifactId] as const,
  },
}
