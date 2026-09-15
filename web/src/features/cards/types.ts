/**
 * types — формы модуля «Тренажёр»: зеркало HTTP службы и общие для экранов значения.
 *
 * Строки интерфейса — `src/i18n/ru/cards.json`, ключ = `cards.` + путь внутри файла.
 * Ветки поделены по экранам: `cards.library.*`, `cards.upload.*`, `cards.set.*`,
 * `cards.settings.*`, `cards.common.*` — библиотека, загрузка, набор, настройки и
 * общее; `cards.play.*` — заход и итоги; `cards.generate.*` — создание агентом и
 * черновик. Чужую ветку строками не занимать.
 *
 * ── Карточки и ключи ─────────────────────────────────────────────────────────
 *
 * Карточка опознаётся ключом `key`: это поле `id` карточки в файле или, если id
 * не задан, `q:` + отпечаток нормализованного текста вопроса. По ключу новая версия
 * файла сохраняет прогресс, по нему же пишутся ответы захода.
 *
 * Тексты `q`, `a`, `note` — безопасное подмножество Markdown с формулами `$…$` и
 * `$$…$$`; показывает их `components/CardView`.
 *
 * ── Прогресс ─────────────────────────────────────────────────────────────────
 *
 * «Знаю» — последний ответ по карточке «Да». Считает только служба; сайт показывает
 * доли, но не пересчитывает их из ответов захода.
 */

// ── настройки захода ─────────────────────────────────────────────────────────

/**
 * Порядок вопросов в заходе:
 * `file` — по файлу; `random` — случайно; `topic_seq` — по темам подряд;
 * `topic_random` — по темам, внутри темы случайно; `topics_shuffled` — темы
 * вперемешку, внутри темы подряд.
 */
export type CardOrder = 'file' | 'random' | 'topic_seq' | 'topic_random' | 'topics_shuffled'

export const CARD_ORDERS: readonly CardOrder[] = ['file', 'random', 'topic_seq', 'topic_random', 'topics_shuffled']

/** Какие вопросы брать: все; ещё не знаю (последний «Нет» или не отвечал); только «Нет». */
export type CardInclude = 'all' | 'unknown' | 'wrong'

export const CARD_INCLUDES: readonly CardInclude[] = ['all', 'unknown', 'wrong']

/** Готовые размеры захода; «все» — `SESSION_ALL` (0), своё число — любое от 1 до `SESSION_SIZE_MAX`. */
export const SESSION_SIZES: readonly number[] = [5, 10, 20, 50]

/** `session_size: 0` — все подходящие карточки. */
export const SESSION_ALL = 0

export const SESSION_SIZE_MAX = 10_000

/**
 * «Без темы» там, где нужна строка: значение `topic=` в запросе списка карточек
 * (`GET …/sets/{id}/cards?topic=-`) и ключ темы на экранах. Служба понимает то же
 * значение. Slug темы у ядра — латиница, цифры и дефисы без дефисов по краям, поэтому
 * одиночный `-` с настоящей темой не совпадёт. В ответах службы «без темы» — `null`
 * (`topic` карточки, `my_progress.by_topic[].topic`), в настройках — `null` в списке `topics`.
 */
export const NO_TOPIC = '-'

/** Элемент списка тем настроек: `Topic.id` или `null` — карточки без темы. */
export type TopicChoice = string | null

/**
 * Настройки захода. Одна форма и у рекомендуемых настроек набора (`defaults`), и у
 * личных настроек человека (`my_settings`).
 */
export interface CardSettings {
  /** Вопросов за заход; `0` — все. */
  session_size: number
  order: CardOrder
  /** Выбранные темы — `Topic.id`, `null` в списке — карточки без темы; `null` вместо списка — все темы. */
  topics: TopicChoice[] | null
  include: CardInclude
  /** Вернуть вопрос с ответом «Нет» через три вопроса, не больше двух раз за заход. */
  repeat_wrong: boolean
}

export const DEFAULT_SETTINGS: CardSettings = {
  session_size: 20,
  order: 'topic_random',
  topics: null,
  include: 'all',
  repeat_wrong: true,
}

/** Настройки из ответа службы: пропущенное или незнакомое поле — значение из `base`. */
export function settingsOf(raw: Partial<CardSettings> | null | undefined, base: CardSettings = DEFAULT_SETTINGS): CardSettings {
  const s = raw ?? {}
  const size = s.session_size as number | null | undefined
  return {
    session_size:
      size === null || size === 0
        ? SESSION_ALL
        : typeof size === 'number' && size >= 1
          ? Math.min(Math.floor(size), SESSION_SIZE_MAX)
          : base.session_size,
    order: s.order && CARD_ORDERS.includes(s.order) ? s.order : base.order,
    topics:
      s.topics === null
        ? null
        : Array.isArray(s.topics)
          ? s.topics.filter((x): x is TopicChoice => x === null || typeof x === 'string')
          : base.topics,
    include: s.include && CARD_INCLUDES.includes(s.include) ? s.include : base.include,
    repeat_wrong: typeof s.repeat_wrong === 'boolean' ? s.repeat_wrong : base.repeat_wrong,
  }
}

/** Совпадают ли две формы настроек по смыслу (порядок выбранных тем не важен). */
export function sameSettings(a: CardSettings, b: CardSettings): boolean {
  const темы = (x: TopicChoice[] | null) => (x === null ? null : x.map((id) => id ?? NO_TOPIC).sort().join('\n'))
  return (
    a.session_size === b.session_size &&
    a.order === b.order &&
    a.include === b.include &&
    a.repeat_wrong === b.repeat_wrong &&
    темы(a.topics) === темы(b.topics)
  )
}

// ── проблемы разбора ─────────────────────────────────────────────────────────

/**
 * Проблема разбора файла:
 * `{path: 'cards[12].a', card: 12, line: null, code: 'empty_answer', text: 'у карточки нет ответа'}`.
 */
export interface Problem {
  /**
   * Номер строки файла с единицы: у битого JSON — место ошибки, у CSV/TSV — строка
   * таблицы; `null` — у проблемы нет строки.
   */
  line: number | null
  /** Столбец в строке `line` с единицы — у битого JSON. */
  column?: number | null
  /** Путь в JSON набора: `cards[12].a`, `defaults.order`; нет — проблема без места в JSON. */
  path?: string | null
  /**
   * Номер карточки с нуля — индекс в массиве `cards`; человеку показывать `card + 1`.
   * `null` — проблема всего файла, а не карточки.
   */
  card?: number | null
  code: string
  text: string
}

// ── библиотека ───────────────────────────────────────────────────────────────

/** Набор в библиотеке пространства (`GET /api/cards/sets`). */
export interface CardSetInfo {
  project_id: string
  set_id: string
  title: string
  /** Число тем. */
  topics: number
  /** Число карточек. */
  cards: number
  /** Сколько карточек набора я знаю (последний ответ «Да»). */
  my_known: number
  updated_at: string | null
}

// ── набор ────────────────────────────────────────────────────────────────────

export interface CardTopic {
  /** slug от заголовка `#`, уникальный в наборе. */
  id: string
  title: string
}

export interface KnownCount {
  known: number
  total: number
}

/** Прогресс по одной теме: `topic` — id темы, `null` — карточки без темы (у них пустой `title`). */
export interface TopicProgress extends KnownCount {
  topic: string | null
  title: string
}

export interface CardProgress extends KnownCount {
  /** Темы в порядке файла; карточки без темы, если есть, — первой строкой с `topic: null`. */
  by_topic: TopicProgress[]
}

/** Мой незаконченный заход набора: `pos` — сколько разных карточек оценено, `total` — сколько их в заходе. */
export interface OpenSessionInfo {
  session_id: string
  pos: number
  total: number
  started_at: string | null
}

/** Набор целиком без карточек (`GET /api/projects/{p}/cards/sets/{id}`). */
export interface CardSet {
  title: string
  description: string
  topics: CardTopic[]
  cards_count: number
  /** Рекомендуемые настройки набора. */
  defaults: CardSettings
  /** Номер версии файла набора; растёт с каждой заменой. */
  version: number
  /** Мои настройки; пока человек их не менял, служба отдаёт рекомендуемые. */
  my_settings: CardSettings | null
  my_progress: CardProgress
  /** Незаконченный заход текущей версии моложе 12 часов — с любого устройства. */
  open_session?: OpenSessionInfo | null
  /** Может ли спрашивающий менять набор (владелец или редактор пространства). */
  can_edit?: boolean
}

export type CardAnswer = 'yes' | 'no'

/** Карточка набора (`GET …/sets/{id}/cards`). */
export interface CardItem {
  key: string
  /** id темы; `null` — без темы. */
  topic: string | null
  q: string
  a: string
  note: string | null
  /** Вопрос поменялся в новой версии файла, прогресс сохранён. */
  changed: boolean
  /** Мой последний ответ; `null` — не отвечал. */
  my_last: CardAnswer | null
}

export interface CardsPage {
  cards: CardItem[]
  total: number
}

/** Запрос страницы карточек: `[from, to)`, поиск по тексту и тема (`NO_TOPIC` — без темы). */
export interface CardsQuery {
  from?: number
  to?: number
  q?: string
  topic?: string | null
}

// ── загрузка и замена ────────────────────────────────────────────────────────

export interface PreviewStats {
  cards: number
  topics: number
  /** Сколько карточек годны (без проблем). */
  valid?: number
  /** Сколько карточек отброшены из-за проблем. */
  rejected?: number
}

/**
 * Годные и все карточки превью — для «Создать только годные (N из M)». Без чисел
 * службы — `null`: подпись идёт без чисел, чтобы не показать догадку.
 */
export function validOf(stats: PreviewStats | undefined): { valid: number; total: number } | null {
  if (!stats || typeof stats.valid !== 'number') return null
  const total = stats.valid + (typeof stats.rejected === 'number' ? stats.rejected : Math.max(0, stats.cards - stats.valid))
  return { valid: stats.valid, total: Math.max(total, stats.valid) }
}

/** Проблемы файла целиком (`card: null`) — с ними набор не создать даже из годных карточек. */
export function hasFileProblems(problems: Problem[]): boolean {
  return problems.some((p) => p.card === null)
}

/** Превью загрузки (`POST /api/cards/preview`): черновик на томе и его проблемы. */
export interface PreviewResult {
  draft_id: string
  problems: Problem[]
  stats: PreviewStats
}

/**
 * Изменения при замене файла — списки ключей карточек: новые, изменённые (ключ тот же,
 * текст вопроса или ответа другой) и удалённые. Числами отвечает сама замена (`ReplaceDone`).
 */
export interface CardsDiff {
  added: string[]
  changed: string[]
  removed: string[]
}

/** Сколько ключей в поле `diff`. */
export function diffCount(v: readonly string[] | undefined): number {
  return v?.length ?? 0
}

/** Ответ `POST …/sets/{id}/replace`: новая версия и число новых, изменённых и удалённых карточек. */
export interface ReplaceDone {
  version: number
  added: number
  changed: number
  removed: number
}

/** Превью замены (`POST …/sets/{id}/replace/preview`). */
export interface ReplacePreview {
  draft_id: string
  problems: Problem[]
  diff: CardsDiff
  stats?: PreviewStats
}

export interface CreatedSet {
  project_id: string
  set_id: string
}

// ── заход ────────────────────────────────────────────────────────────────────

/** Быстрый старт: по моим настройкам; только мои «Нет»; весь набор по файлу. */
export type SessionPreset = 'settings' | 'wrong' | 'all_file'

/** Заведённый заход (`POST …/sets/{id}/sessions`): порядок ключей и первые карточки. */
export interface SessionStart {
  session_id: string
  keys: string[]
  /** Первые карточки захода по порядку `keys` (до 20). */
  cards: CardItem[]
}

/** Записанный ответ захода. */
export interface SessionAnswer {
  key: string
  answer: CardAnswer
  shown: boolean
  ms: number
  client_seq: number
  /** `client_seq` ответа, который этот исправляет («Изменить»). */
  corrects?: number | null
}

/** Заход (`GET …/sessions/{sid}`, `GET …/sets/{id}/sessions/open`): порядок, позиция и ответы. */
export interface SessionState {
  session_id?: string
  keys: string[]
  pos: number
  answers: SessionAnswer[]
}

/** Тело `POST …/sessions/{sid}/answers`. */
export type AnswerBody = SessionAnswer

// ── агент и черновики ────────────────────────────────────────────────────────

export type GenerateLength = 'short' | 'full'

/** Тело `POST /api/cards/generate`. `project_id` + `set_id` — дополнить существующий набор. */
export interface GenerateBody {
  workspace_id: string
  project_id?: string
  set_id?: string
  prompt: string
  /** Список вопросов к экзамену, по строке на вопрос; темы — по разделам списка. */
  questions?: string
  material_ids?: string[]
  /** Сколько карточек всего, до 200 за раз. */
  count: number
  /** Сколько карточек на каждую тему вместо счёта на весь набор; `null` — счёт всего. */
  per_topic?: number | null
  length: GenerateLength
  language: string
  /** Пресет модели, который платит за генерацию. */
  endpoint: string
}

export interface GenerateStarted {
  job_id: string
  draft_id: string
}

/** Карточка разобранного набора — форма ядра. */
export interface DraftCard {
  key: string
  q: string
  a: string
  topic: string | null
  note: string | null
  explicit_id: boolean
}

/**
 * Разобранный набор черновика — форма ядра. Рекомендуемые настройки здесь сырые, как их
 * записал файл: темы — только id, без `null`.
 */
export interface DraftSet {
  title: string
  description: string
  language: string
  topics: CardTopic[]
  cards: DraftCard[]
  defaults: {
    session_size: number | null
    order: string
    topics: string[] | null
    include: string
    repeat_wrong: boolean
  }
}

/** Черновик (`GET /api/cards/drafts/{draft_id}`). `set: null` — файл не разобрался вовсе. */
export interface Draft {
  set: DraftSet | null
  problems: Problem[]
  source: 'upload' | 'agent'
  job_id: string | null
  /** JSON-строка набора черновика со всеми карточками, включая отклонённые. */
  text: string
  /** Годные и отброшенные карточки. */
  stats: { valid: number; rejected: number }
}

/** Ответ `PUT /api/cards/drafts/{draft_id}`. */
export interface DraftUpdated {
  problems: Problem[]
  stats: PreviewStats
}

/** Тело `POST /api/cards/drafts/{draft_id}/save`: новый набор в пространстве или новая версия набора. */
export type DraftSaveBody = { workspace_id: string } | { project_id: string; set_id: string }

// ── доли ─────────────────────────────────────────────────────────────────────

/** Процент «знаю», целым числом; пустой набор — 0. */
export function knownPercent(known: number, total: number): number {
  if (!total || total <= 0) return 0
  return Math.round((Math.max(0, Math.min(known, total)) / total) * 100)
}
