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
 * Новой области: заводите свои ключи здесь же, отдельным полем; файл
 * дописывается, а не переписывается.
 */

export const keys = {
  /**
   * Сводка первого экрана (`GET /api/bootstrap`). Своим ключом, а не под
   * `me`: сводка спрашивается один раз за загрузку, а её части дальше живут
   * своими ключами, и сброс `me` не должен тянуть за собой ещё четыре ответа.
   */
  bootstrap: ['bootstrap'] as const,
  me: ['me'] as const,
  modules: ['modules'] as const,
  usage: ['usage'] as const,
  notifications: ['notifications'] as const,
  jobs: {
    all: ['jobs'] as const,
    list: (status?: string) => ['jobs', 'list', status ?? 'all'] as const,
    /**
     * Задания, которые считаются прямо сейчас, в одном пространстве.
     * Пространство входит в ключ по той же причине, что и у списка работ:
     * шапка и дашборд показывают то, что происходит там, где человек работает,
     * и после переключения список обязан смениться, а не устареть молча.
     */
    active: (workspaceId: string) => ['jobs', 'list', 'active', workspaceId] as const,
    one: (id: string) => ['jobs', 'one', id] as const,
    /**
     * Задания одного проекта — из них панель агента берёт историю прогонов.
     * Ключ начинается с `jobs` намеренно: постановка задания уже гасит
     * `keys.jobs.all`, и своего корня, который никто не сбрасывает, здесь не
     * заводится.
     */
    ofProject: (projectId: string) => ['jobs', 'list', 'project', projectId] as const,
  },
  // Пространства, проекты и материалы.
  workspaces: {
    all: ['workspaces'] as const,
    personal: ['workspaces', 'personal'] as const,
    /** Список пространств человека; корзина — отдельный список, не фильтр. */
    list: (trash: boolean) => ['workspaces', 'list', trash ? 'trash' : 'active'] as const,
    /** Участники одного пространства. Под корнем `workspaces`: смена роли
     *  обязана гаситься вместе с карточкой пространства. */
    members: (workspaceId: string) => ['workspaces', workspaceId, 'members'] as const,
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
    /**
     * Журнал запусков работы. Под корнем `projects.one`, как теги и значения:
     * запуски принадлежат работе, и сброс работы обязан гасить их заодно —
     * иначе созданный отчёт не появится в списке до перезагрузки страницы.
     * Порядок входит в ключ: это разные ответы службы, а не разный вид одного.
     */
    runs: (projectId: string, sort: string) =>
      ['projects', 'one', projectId, 'runs', sort] as const,
    /**
     * Бланки, приложенные к работе. Свои бланки — отдельный корень.
     *
     * Отчёт входит в ключ, потому что в ответе есть пометка «по этому бланку
     * собирается», а собираются разные отчёты работы по разным бланкам. Общий
     * ключ показывал бы пометку первого открытого отчёта на всех остальных.
     */
    projectTemplates: (projectId: string, report = '') =>
      ['projects', 'one', projectId, 'templates', report] as const,
    /**
     * Тот же список, но всеми отчётами сразу, — корень для сброса. Приложенный
     * или отвязанный бланк виден из каждого отчёта работы, и гасить только тот
     * отчёт, из которого нажали, значило бы показать соседнему список без
     * только что приложенного файла.
     */
    projectTemplatesAll: (projectId: string) =>
      ['projects', 'one', projectId, 'templates'] as const,
    /** Отчёты работы — карточки списка на главной модуля. */
    reports: (projectId: string) => ['projects', 'one', projectId, 'reports'] as const,
  },
  // Отчёты. Ключи начинаются с `projects`, а не со своего корня,
  // намеренно: теги и значения принадлежат проекту, и сброс проекта
  // (`invalidateQueries({ queryKey: keys.projects.one(id) })`) обязан гасить их
  // заодно — иначе после переименования или смены шаблона экран работы покажет
  // прежний список тегов и не заметит этого.
  //
  // Отчёт входит в ключ отдельным звеном: отчётов в работе несколько, у каждого
  // свой бланк, свои теги, свои значения и своя история версий, и общий ключ
  // означал бы одну строку кэша на два разных документа — то есть чужие
  // значения в полях после перехода между отчётами. Пустое звено — единственный
  // документ работы, каким её видели, пока отчёт в ней был один.
  reports: {
    tags: (projectId: string, report = '') =>
      ['projects', 'one', projectId, 'tags', report] as const,
    values: (projectId: string, report = '') =>
      ['projects', 'one', projectId, 'values', report] as const,
    versions: (projectId: string, report: string, key: string) =>
      ['projects', 'one', projectId, 'versions', report, key] as const,
    version: (projectId: string, report: string, key: string, n: number) =>
      ['projects', 'one', projectId, 'versions', report, key, n] as const,
  },
  // Область «Задания» (kadai). Ключи работы начинаются с `projects.one`, как у
  // отчётов, и по той же причине: ход работы, блоки и их версии принадлежат
  // проекту, и сброс проекта обязан гасить их заодно. Список стадий — свой
  // корень: он один на всю службу и от проекта не зависит.
  // Решение входит в ключ отдельным звеном: решений в работе несколько, у
  // каждого свой ход стадий, свои блоки и свои пожелания, и общий ключ показал
  // бы на экране второго решения ответ, полученный для первого. Пустое звено —
  // работа целиком, какой её видели, пока решение в ней было одно.
  kadai: {
    stageNames: ['kadai', 'stages'] as const,
    runs: (projectId: string) => ['projects', 'one', projectId, 'kadai-runs'] as const,
    status: (projectId: string, runId = '') =>
      ['projects', 'one', projectId, 'kadai', runId] as const,
    blocks: (projectId: string, runId = '') =>
      ['projects', 'one', projectId, 'blocks', runId] as const,
    blockVersions: (projectId: string, runId = '') =>
      ['projects', 'one', projectId, 'block-versions', runId] as const,
    blockVersion: (projectId: string, runId: string, n: number) =>
      ['projects', 'one', projectId, 'block-versions', runId, n] as const,
    wishes: (projectId: string, runId = '') =>
      ['projects', 'one', projectId, 'kadai-wishes', runId] as const,
    /** Папка контекста решения: опись его файлов, а не всей работы. */
    context: (projectId: string, runId: string) =>
      ['projects', 'one', projectId, 'kadai-context', runId] as const,
    /** Общие файлы работы с галочками решения: галочки у решений разные. */
    common: (projectId: string, runId: string) =>
      ['projects', 'one', projectId, 'kadai-common', runId] as const,
  },
  // Настройки аккаунта.
  modelKeys: ['model-keys'] as const,
  /** Свои шаблоны отчётов: их читают и настройки, и диалог «Новая работа». */
  templates: ['templates'] as const,
  keyProviders: ['key-providers'] as const,
  apiTokens: ['api-tokens'] as const,
  // Админка. Всё под одним корнем, чтобы правка человека гасила и
  // список, и его карточку одним `invalidateQueries({ queryKey: ['admin'] })`.
  admin: {
    all: ['admin'] as const,
    users: (limit: number) => ['admin', 'users', limit] as const,
    queue: ['admin', 'queue'] as const,
    security: (kind: string | null, limit: number) =>
      ['admin', 'security', kind ?? 'all', limit] as const,
    /** Ряды графиков «Обзора»; период — часть ключа, иначе 7 и 90 дней делили
     *  бы одну строку кэша. */
    stats: (days: number) => ['admin', 'stats', days] as const,
    /** Справочник планов. Под тем же корнем, что и люди: правка человека его
     *  не меняет, но лишний запрос справочника дешевле разъехавшегося кэша. */
    plans: ['admin', 'plans'] as const,
  },
  // Схемы. Ключи свои, а не чужие `projects.*`, намеренно: под теми
  // лежат формы проектов, и гасить их своим списком схем значило бы сбрасывать
  // чужой кэш ради своего.
  diagrams: {
    all: ['diagrams'] as const,
    modes: ['diagrams', 'modes'] as const,
    themes: ['diagrams', 'themes'] as const,
    /**
     * Работы текущего пространства — по ним собирается список схем.
     * Пространство входит в ключ: без него переключение показывало бы прежний
     * список работ до тех пор, пока ответ не устареет сам.
     */
    projects: (workspaceId: string) => ['diagrams', 'projects', workspaceId] as const,
    /**
     * Сохранённые схемы одного модуля в одной работе. Модуль входит в ключ:
     * у блок-схем и UML свои списки, и общий ключ показывал бы одному из них
     * содержимое другого.
     */
    list: (module: string, projectId: string) => ['diagrams', 'list', module, projectId] as const,
    /** Одна сохранённая схема: XML, исходники и параметры. */
    one: (module: string, projectId: string, runId: string) =>
      ['diagrams', 'one', module, projectId, runId] as const,
    /** Содержимое артефакта схемы — тот самый XML draw.io. */
    artifact: (projectId: string, artifactId: string) =>
      ['diagrams', 'artifact', projectId, artifactId] as const,
  },
  // Палитра поиска (Ctrl+K). Свой корень, а не `projects.*`: под тем лежит
  // список работ, а здесь — выдача по строке, и гасить чужой список своим
  // поиском значило бы перезапрашивать экран проектов впустую.
  search: {
    all: ['search'] as const,
    /**
     * Запрос службе: ключ несёт пространство и саму строку. Пространство — не
     * украшение: поиск ищет только в текущем, и без него выдача, найденная в
     * одном пространстве, показывалась бы в другом.
     */
    query: (workspaceId: string, q: string) => ['search', 'query', workspaceId, q] as const,
  },
}
