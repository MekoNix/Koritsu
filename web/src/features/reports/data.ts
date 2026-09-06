/**
 * data — запросы области «Отчёты» одним файлом.
 *
 * То же правило, что у проектов: адрес маршрута, форма ответа и список
 * ключей, которые сбрасываются после изменения, — одно знание, и живёт оно в
 * одном месте. Экраны зовут хуки, а не `api.GET`.
 *
 * Общее с проектами (карточка проекта, материалы, постановка задания, адрес
 * артефакта) берётся из `@/features/projects/data` и здесь не повторяется:
 * второй `useProject` рядом с первым — это два кэша одного проекта, которые
 * расходятся после переименования.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'
import { СВЕЖЕСТЬ_ПОД_ПОТОКОМ } from '@/features/projects/data'
import { useMe } from '@/api/hooks'

import type { ReportTemplate } from '@/features/projects/types'

import type {
  ProjectReport,
  ProjectTagsBody,
  ProvidersBody,
  TagValue,
  ValueWritten,
  ValuesBody,
  VersionBody,
  VersionHead,
  VersionsBody,
  WorkspaceReport,
} from './types'

// ── отчёты работы ────────────────────────────────────────────────────────────
// В работе несколько отчётов, у каждого свой бланк, свои значения тегов с
// историей и свои сборки. Отчёт — это запись журнала запусков (`module:
// "reports"`) и каталог документа рядом с ней, поэтому идентификатор отчёта
// (`run_id`) — то самое, что все остальные запросы области передают как
// `report`.

/** Отчёты работы карточками: имя, номер, бланк, картинка первой страницы. */
export function useProjectReports(projectId: string | undefined): UseQueryResult<ProjectReport[]> {
  return useQuery({
    queryKey: keys.projects.reports(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<ProjectReport[]>(
        api.GET('/api/projects/{project_id}/reports', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

/**
 * Отчёты всех работ пространства одной лентой, новые сверху.
 *
 * Маршрутом службы, а не запросом на каждую работу: главная модуля показывает
 * написанное человеком сразу, без выбора работы, и собирать эту ленту из
 * списка работ плюс запроса на каждую значило бы ответ, время которого растёт
 * вместе с числом работ.
 */
export function useWorkspaceReports(
  workspaceId: string | undefined,
): UseQueryResult<WorkspaceReport[]> {
  return useQuery({
    queryKey: keys.projects.workspaceReports(workspaceId ?? ''),
    enabled: !!workspaceId,
    queryFn: () =>
      unwrap<WorkspaceReport[]>(
        api.GET('/api/reports', {
          params: { query: { workspace_id: workspaceId as string } },
        }),
      ),
  })
}

/**
 * Завести отчёт: запись журнала и документ под ней.
 *
 * `templateId` — один из приложенных к работе бланков. Имя не передаётся, когда
 * его не дали: имя по умолчанию рисует сайт из модуля и номера (`n`), который
 * считает служба.
 *
 * Первый отчёт работы забирает её собственный документ — тот, в котором писали
 * значения до появления отчётов, — и остаётся на её бланке, если другого не
 * назвали; все следующие получают свой документ, а без бланка начинают с
 * пустого. Правило это знает служба (`packages/api/projects/reports.py`), и
 * здесь оно не повторяется: сайт заводит любой отчёт одним и тем же запросом, а
 * «который он по счёту» считается в базе. Считать это на сайте значило бы
 * решать вопрос «первый ли» по списку, который в эту минуту мог быть ещё не
 * загружен, — и заводить второй отчёт как первый.
 */
export function useCreateProjectReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      templateId,
      name,
    }: {
      projectId: string
      templateId?: string | null
      name?: string
    }): Promise<ProjectReport> =>
      unwrap<ProjectReport>(
        api.POST('/api/projects/{project_id}/reports', {
          params: { path: { project_id: projectId } },
          body: { template_id: templateId || null, name: name ?? '' },
        }),
      ),
    // Гасится вся работа: отчёт есть и в списке отчётов, и в журнале запусков
    // на её карточке, а два разных ключа на одно событие расходятся на первой
    // же правке. Лента пространства — отдельной строкой: под ключом работы её
    // нет, а новый отчёт обязан появиться в ней тем же действием.
    onSuccess: (_отчёт, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.workspaceReportsAll })
    },
  })
}

/**
 * Снести отчёт: его значения, их версии и каталог сборки.
 *
 * Бланк при этом остаётся приложенным к работе, а артефакты — на томе: артефакт
 * адресуется содержимым и может стоять значением тега в соседнем отчёте.
 *
 * Работа называется вызовом, а не хуком: на главной модуля лежат отчёты всех
 * работ пространства сразу, и хук, знающий одну работу, снёс бы отчёт не из
 * той.
 */
export function useDeleteProjectReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, runId }: { projectId: string; runId: string }) =>
      unwrap<void>(
        api.DELETE('/api/projects/{project_id}/reports/{run_id}', {
          params: { path: { project_id: projectId, run_id: runId } },
        }),
      ),
    onSuccess: (_ничего, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.workspaceReportsAll })
    },
  })
}

// ── теги и значения ──────────────────────────────────────────────────────────

/**
 * Теги шаблона со состоянием заполнения — то, из чего сделана колонка слева.
 *
 * Именно этот маршрут, а не `project.keys`: карточка проекта отдаёт только
 * ключи, а колонке нужны метка, тип и «кто это написал».
 *
 * Отдаётся тело целиком, а не один список тегов: рядом с тегами приезжают
 * непонятные сборщику конструкции бланка (`constructs`), и разделять их на два
 * запроса значило бы дважды разбирать один манифест.
 */
export function useProjectTags(
  projectId: string | undefined,
  report = '',
): UseQueryResult<ProjectTagsBody> {
  return useQuery({
    queryKey: keys.reports.tags(projectId ?? '', report),
    enabled: !!projectId,
    queryFn: async () => {
      const body = await unwrap<ProjectTagsBody>(
        api.GET('/api/projects/{project_id}/tags', {
          params: { path: { project_id: projectId as string }, query: { report } },
        }),
      )
      return body
    },
  })
}

/**
 * Текущие значения всех тегов разом.
 *
 * Разом, а не по одному на выбранный тег: значений столько же, сколько тегов,
 * они короткие, и запрос на каждое переключение в списке — это мигание пустым
 * полем там, где ответ уже лежит в кэше.
 */
export function useProjectValues(
  projectId: string | undefined,
  report = '',
): UseQueryResult<Record<string, TagValue>> {
  return useQuery({
    queryKey: keys.reports.values(projectId ?? '', report),
    enabled: !!projectId,
    queryFn: async () => {
      const body = await unwrap<ValuesBody>(
        api.GET('/api/projects/{project_id}/values', {
          params: { path: { project_id: projectId as string }, query: { report } },
        }),
      )
      return body.values
    },
    // Значения меняют запись рукой и конец прогона, и оба гасят этот ключ
    // сами (`useSetValue`, `useFill`). Перезапрос при возврате на экран
    // добавил бы ответ, содержимое которого уже лежит в кэше.
    staleTime: СВЕЖЕСТЬ_ПОД_ПОТОКОМ,
  })
}

/**
 * Записать значение тега рукой человека.
 *
 * `source` службе не передаётся и передан быть не может: по этому маршруту
 * пишет человек, и пометку ставит служба (`projects/routes.py`). Очистка — это
 * тот же вызов с пустым текстом, а не отдельный маршрут: удаления значения у
 * службы нет, у тега есть история, и «очистить» означает «новая версия, в
 * которой пусто».
 */
export function useSetValue(projectId: string | undefined, report = '') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: TagValue }) =>
      unwrap<ValueWritten>(
        api.PUT('/api/projects/{project_id}/values/{key}', {
          params: { path: { project_id: projectId as string, key }, query: { report } },
          body: value as Record<string, never>,
        }),
      ),
    onSuccess: (_written, { key }) => {
      void qc.invalidateQueries({ queryKey: keys.reports.tags(projectId ?? '', report) })
      void qc.invalidateQueries({ queryKey: keys.reports.values(projectId ?? '', report) })
      void qc.invalidateQueries({ queryKey: keys.reports.versions(projectId ?? '', report, key) })
    },
  })
}

// ── версии значения ──────────────────────────────────────────────────────────

export function useTagVersions(
  projectId: string | undefined,
  report: string,
  key: string | undefined,
): UseQueryResult<VersionHead[]> {
  return useQuery({
    queryKey: keys.reports.versions(projectId ?? '', report, key ?? ''),
    enabled: !!projectId && !!key,
    queryFn: async () => {
      const body = await unwrap<VersionsBody>(
        api.GET('/api/projects/{project_id}/values/{key}/versions', {
          params: {
            path: { project_id: projectId as string, key: key as string },
            query: { report },
          },
        }),
      )
      return body.versions
    },
    // Тег без единого значения отвечает 404 — это не беда, а «истории нет».
    retry: false,
  })
}

/** Одна версия целиком: шапка и само значение — то, что показывают перед «вернуть». */
export function useTagVersion(
  projectId: string | undefined,
  report: string,
  key: string | undefined,
  n: number | null,
): UseQueryResult<VersionBody> {
  return useQuery({
    queryKey: keys.reports.version(projectId ?? '', report, key ?? '', n ?? 0),
    enabled: !!projectId && !!key && n !== null,
    queryFn: () =>
      unwrap<VersionBody>(
        api.GET('/api/projects/{project_id}/values/{key}/versions/{n}', {
          params: {
            path: { project_id: projectId as string, key: key as string, n: n as number },
            query: { report },
          },
        }),
      ),
  })
}

/**
 * Вернуть прошлую версию.
 *
 * Возврат ничего не удаляет: служба дописывает выбранное значение новой
 * версией, и в ответе номер БОЛЬШЕ того, к которому вернулись
 * (`versions/routes.py`). Поэтому список версий после возврата обязан
 * перечитаться — иначе человек увидит историю без своего же действия.
 */
export function useRollbackValue(projectId: string | undefined, report = '') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, n }: { key: string; n: number }) =>
      unwrap<{ key: string; version: VersionHead; restored_from: number }>(
        api.POST('/api/projects/{project_id}/values/{key}/rollback', {
          params: { path: { project_id: projectId as string, key }, query: { report } },
          body: { n },
        }),
      ),
    onSuccess: (_answer, { key }) => {
      void qc.invalidateQueries({ queryKey: keys.reports.tags(projectId ?? '', report) })
      void qc.invalidateQueries({ queryKey: keys.reports.values(projectId ?? '', report) })
      void qc.invalidateQueries({ queryKey: keys.reports.versions(projectId ?? '', report, key) })
    },
  })
}

// ── пресеты модели ───────────────────────────────────────────────────────────

/**
 * Пресеты модели и чем по каждому платить (`own` | `shared` | `none`).
 *
 * Без `key_source` выбор пресета был бы гаданием: свой ключ сайт видит, общий
 * ключ службы не виден ниоткуда, кроме этого ответа, и пресет, которым платить
 * нечем, даёт отказ вместо работы.
 */
export function useProviders(): UseQueryResult<ProvidersBody> {
  return useQuery({
    queryKey: keys.keyProviders,
    queryFn: () => unwrap<ProvidersBody>(api.GET('/api/keys/providers')),
    staleTime: 5 * 60_000,
  })
}

/**
 * Какой пресет предложить по умолчанию: сначала свой ключ, потом общий.
 *
 * Свой вперёд общего по той же причине, по которой их так же выбирает служба
 * (`keys/service.resolve_key`): человек завёл ключ затем, чтобы расход был
 * виден у него. `null` — платить нечем ни по одному пресету, и экран обязан
 * сказать это словами до нажатия, а не отказом после.
 */
export function defaultProvider(body: ProvidersBody | undefined): string | null {
  if (!body) return null
  const source = body.key_source ?? {}
  return (
    body.providers.find((p) => source[p] === 'own') ??
    body.providers.find((p) => source[p] === 'shared') ??
    null
  )
}

/**
 * Что подставить в выбор пресета: выбор человека, а если его нет — правило
 * сайта (`defaultProvider`).
 *
 * Выбор живёт в профиле (`me.default_endpoint`, раздел настроек «Агент и
 * модели»), а не в браузере: человек открывает работу и с ноутбука, и с чужой
 * машины, и умолчание, оставшееся в `localStorage` первой, на второй молча
 * исчезло бы.
 *
 * Хуком, а не аргументом `defaultProvider`: профиль читается тем же
 * `useMe`, что и вся оболочка, и просить каждый экран передать его сюда
 * значило бы четыре одинаковых строки в четырёх местах.
 */
export function useDefaultEndpoint(): string | null {
  const me = useMe()
  const providers = useProviders()
  return me.data?.default_endpoint ?? defaultProvider(providers.data)
}

/**
 * Задание модели на один тег — поле рядом с заполнением.
 *
 * Живёт в манифесте работы, а не в прогоне: написанное однажды («сухо, без
 * оценок») действует и завтра, и после смены бланка. Общая подсказка на весь
 * прогон — другое поле и другой путь (`useFill`), и путать их нельзя: первая
 * про этот тег навсегда, вторая про сегодняшний запуск.
 */
export function useSetTagPrompt(projectId: string | undefined, report = '') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, prompt }: { key: string; prompt: string }) =>
      unwrap<{ key: string; prompt: string }>(
        api.PATCH('/api/projects/{project_id}/tags/{key}', {
          params: { path: { project_id: projectId as string, key }, query: { report } },
          body: { prompt },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.reports.tags(projectId ?? '', report) })
    },
  })
}

/**
 * Собирать работу по этому приложенному бланку.
 *
 * Гасит и список бланков (у одного из них меняется пометка «выбран»), и теги
 * со значениями: манифест перестроен, и колонка тегов теперь другая.
 */
export function useUseProjectTemplate(projectId: string | undefined, report = '') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ templateId }: { templateId: string }) =>
      unwrap<ReportTemplate>(
        api.POST('/api/projects/{project_id}/templates/{template_id}/use', {
          params: {
            path: { project_id: projectId as string, template_id: templateId },
            query: { report },
          },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.projects.projectTemplatesAll(projectId ?? '') })
      void qc.invalidateQueries({ queryKey: keys.reports.tags(projectId ?? '', report) })
      void qc.invalidateQueries({ queryKey: keys.reports.values(projectId ?? '', report) })
      // Карточка отчёта в списке называет бланк и число тегов — после смены
      // бланка это другие слова, и оба списка обязаны узнать их тем же
      // действием.
      void qc.invalidateQueries({ queryKey: keys.projects.reports(projectId ?? '') })
      void qc.invalidateQueries({ queryKey: keys.projects.workspaceReportsAll })
    },
  })
}
