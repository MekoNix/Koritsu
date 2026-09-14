/**
 * BoardPage — экран доски: холст во всю ширину, панель репетитора справа.
 *
 * Раскладка «лист с призраком»: человек пишет от руки, а прочитанное стои́т
 * набранной формулой **прямо под своей рукописной строкой** на холсте
 * (`Ghosts.tsx`) — там же его и правят, нажатием на призрака. Панель справа
 * занята перепиской с репетитором, а строки в ней — вложение к просьбе; в рейку
 * она складывается одним нажатием.
 *
 * **Где что живёт.** Сцена — состояние редактора и запись на томе; распознанное
 * — словарь по строкам (`recognizer.ts`), который уезжает на том рядом со
 * сценой, чтобы после перезагрузки страницы не распознавать заново ничего;
 * выноски — наложение над холстом, а не элементы сцены: они принадлежат прогону,
 * а не решению человека, и переживать перезагрузку не обязаны.
 *
 * **Три таймера от одного изменения, и у каждого своя причина.** Всё на этом
 * экране считается от паузы, а не от события: письмо — это поток правок по
 * десятку в секунду, и делать на каждую из них работу нельзя.
 *
 *   250 мс  пересчёт групп росчерков в строки — по нему едут призраки;
 *   700 мс  чтение грязных строк: те, что разошлись со своим отпечатком;
 *  1500 мс  запись сцены на том.
 *
 * **Почему состояние холста лежит в `ref`, а не в `useState`.** `onChange`
 * прилетает на каждую точку росчерка и на каждый кадр панорамы. Держать React в
 * такт с этим потоком нельзя — письмо превратится в поток перерисовок. Поэтому
 * данные лежат в ссылках, а перерисовка просится не чаще кадра.
 *
 * **Общей панели агента на этом экране нет.** Она шлёт задание вида `agent`, а
 * оно на доске отказалось бы ещё до вызова модели: у доски свой репетитор, своё
 * задание и своя цена. Список разделов, где панель прячется, — в
 * `features/agent/context.ts`.
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { errorText, isApiError } from '@/api'
import { useUsage } from '@/api/hooks'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { BASE_PATH } from '@/lib/basePath'
import { useAppearance } from '@/theme'
import { Button, ErrorState, Icon, SkeletonLines } from '@/ui'
import { useDefaultEndpoint } from '@/features/reports/data'
import { useWidePage } from '@/app/shell/widePage'

import { highlightRect, inView, type Rect } from './callouts'
import {
  recognizeLines,
  useBoardChat,
  useBoardScene,
  useBoardTask,
  useBoards,
  useInkSession,
  useRebuildSteps,
  useSaveScene,
  useSetBoardTask,
} from './data'
import { Ghosts } from './Ghosts'
import { INK_STATES, InkPen, now, type InkState } from './ink'
import {
  fairCopy,
  pruneRecognized,
  readCache,
  recognizedFromScene,
  sceneLines,
  syncPlaces,
  typeLine,
  willSee,
  type FairLine,
  type RecognizedCache,
  type SceneLine,
} from './recognizer'
import { sceneToJSON, type SceneElement } from './scene'
import { FingerPan, PenWatch, type ViewState } from './strokes'
import { TutorPanel, type Editing, type PendingMessage } from './TutorPanel'
import { useBoardCheck } from './useBoardCheck'
import { BOARD_CHECK, SCENE_STALE, type InkSession } from './types'

/**
 * Редактор грузится отдельным куском и только здесь.
 *
 * `EXCALIDRAW_ASSET_PATH` ставится **до** загрузки модуля: редактор читает эту
 * переменную в момент своей загрузки, и промах означает, что двести с лишним
 * шрифтов сцены молча уедут на чужой CDN. Присваивание внутри модуля с обычным
 * импортом было бы поздним — импорты поднимаются выше кода.
 */
const Excalidraw = lazy(async () => {
  ;(window as Window & { EXCALIDRAW_ASSET_PATH?: string }).EXCALIDRAW_ASSET_PATH = `${BASE_PATH}/`
  const модуль = await import('@excalidraw/excalidraw')
  await import('@excalidraw/excalidraw/index.css')
  return { default: модуль.Excalidraw }
})

/**
 * Что убрано из редактора. Картинок на доске в v1 нет: каждое сохранение росло
 * бы на их размер, а модели картинка всё равно не уезжает. Один объект на модуль
 * — редактор сравнивает свойства, и новый литерал на каждый рендер обновлял бы его
 * впустую.
 */
const ПАРАМЕТРЫ_РЕДАКТОРА = {
  canvasActions: { loadScene: false, saveToActiveFile: false, export: false as const },
  tools: { image: false },
}

/** Через сколько тишины сцена уезжает на том. Чаще — запись на каждой точке. */
const ЗАДЕРЖКА_СОХРАНЕНИЯ = 1500

/**
 * Через сколько тишины росчерки пересобираются в строки.
 *
 * Заметно меньше паузы распознавания: к моменту запроса группы обязаны быть
 * свежими, а призрак перенесённой строки должен уехать за ней почти сразу.
 * Делать это на каждый кадр нельзя — группировка читает точки всех росчерков
 * доски, а их тысячи.
 */
const ЗАДЕРЖКА_ГРУПП = 250

/** Уже этого панель не тянется: поле сообщения и скрепка должны помещаться. */
const PANEL_MIN = 300
/** Ширина панели по умолчанию, пока человек её не тянул. */
const PANEL_DEFAULT = 420
const PANEL_KEY = 'koritsu.board.panel'

function readPanelWidth(): number {
  try {
    const n = Number(localStorage.getItem(PANEL_KEY))
    return Number.isFinite(n) && n >= PANEL_MIN ? n : PANEL_DEFAULT
  } catch {
    return PANEL_DEFAULT
  }
}

function writePanelWidth(n: number): void {
  try {
    localStorage.setItem(PANEL_KEY, String(n))
  } catch {
    // Хранилище недоступно — ширина живёт до перезагрузки, и этого хватит.
  }
}

/** Ручка редактора в том объёме, в каком её трогает доска. */
type BoardApi = {
  getSceneElements: () => readonly SceneElement[]
  getAppState: () => ViewState & {
    viewBackgroundColor?: string
    gridSize?: number | null
    selectedElementIds?: Record<string, boolean>
  }
  updateScene: (сцена: {
    elements?: SceneElement[]
    appState?: Record<string, unknown>
    captureUpdate?: 'IMMEDIATELY' | 'NEVER' | 'EVENTUALLY'
  }) => void
  setActiveTool: (инструмент: { type: string }) => void
}

export function BoardPage() {
  const t = useT()
  const navigate = useNavigate()
  useWidePage()
  const { projectId = '', boardId = '' } = useParams()
  const { appearance } = useAppearance()

  const boards = useBoards(projectId)
  const scene = useBoardScene(projectId, boardId)
  const task = useBoardTask(projectId, boardId)
  const session = useInkSession()
  const usage = useUsage()
  const endpoint = useDefaultEndpoint()

  const saveScene = useSaveScene()
  const rebuild = useRebuildSteps()
  const setTask = useSetBoardTask()
  // Сами мутации пересобираются на каждый рендер, а их `mutate` — нет. Отложенное
  // сохранение зависит именно от `mutate`: иначе любая перерисовка сбрасывала бы
  // таймер, и сцена уезжала бы на том только после того, как человек замрёт.
  const сохранитьСцену = saveScene.mutate
  const пересобрать = rebuild.mutate
  // Те же две записи, но с ожиданием: перед просьбой к репетитору они идут
  // цепочкой, и «дальше» означает «после того, как том ответил».
  const сохранитьСценуЖдя = saveScene.mutateAsync
  const пересобратьЖдя = rebuild.mutateAsync

  const ручка = useRef<BoardApi | null>(null)
  const элементы = useRef<SceneElement[]>([])
  const вид = useRef<ViewState & { viewBackgroundColor?: string; gridSize?: number | null }>({})
  const кадр = useRef(0)
  const [тик, тикнуть] = useState(0)
  // Отдельный счётчик для вида (прокрутка, масштаб, размер): по нему
  // перерисовываются призраки, и только они. Сцену он не трогает.
  const [, тикнутьВид] = useState(0)
  const кадрВида = useRef(0)
  const подписьСцены = useRef('')

  /** Версия сцены на томе. Ссылкой, потому что её читает отложенное сохранение. */
  const версия = useRef(0)
  const [версияЭкрана, setВерсияЭкрана] = useState(0)
  const грязно = useRef(false)
  const [конфликт, setКонфликт] = useState(false)

  const [свёрнута, setСвёрнута] = useState(false)
  /** Выделенные на холсте элементы: по ним сужается вложение к сообщению. */
  const [выделение, setВыделение] = useState<Set<string>>(() => new Set())
  const подписьВыделенияБыла = useRef('')
  /** Ширина панели в px на широком экране; тянется за ручку и помнится. */
  const [ширинаПанели, setШиринаПанели] = useState<number>(() => readPanelWidth())
  const страница = useRef<HTMLDivElement | null>(null)
  const [воВесьЭкран, setВоВесьЭкран] = useState(false)
  const [подсветка, setПодсветка] = useState<string[] | null>(null)

  /**
   * Строки сцены и распознанное по ним — каждое в двух видах.
   *
   * Ссылка нужна тому, кто читает их вне отрисовки: перу на паузе и обработчикам
   * нажатий. Состояние — тому, кто их показывает. Держать одно вместо другого
   * нельзя: ссылка не перерисовывает экран, а состояние не видно из замыкания,
   * созданного однажды.
   */
  const строки = useRef<SceneLine[]>([])
  const [строкиЭкрана, setСтрокиЭкрана] = useState<SceneLine[]>([])
  const кэш = useRef<RecognizedCache>({})
  const [кэшЭкрана, setКэшЭкрана] = useState<RecognizedCache>({})
  const загружено = useRef(false)
  /** Разметку старой доски вычитываем один раз за жизнь экрана. */
  const перенесено = useRef(false)
  const [правка, setПравка] = useState<Editing | null>(null)
  /**
   * Сообщение, отправленное и ещё не записанное на том.
   *
   * Здесь, а не в панели: панель складывается в рейку, и сообщение, жившее
   * внутри неё, пропадало бы вместе с ней. Сама переписка лежит на томе и
   * читается оттуда (`useBoardChat`).
   */
  const [ожидание, setОжидание] = useState<PendingMessage | null>(null)
  const chat = useBoardChat(projectId, boardId)

  const [инк, setИнк] = useState<{ state: InkState; note: string }>({
    state: INK_STATES.off,
    note: '',
  })
  const перо = useRef<InkPen | null>(null)
  const стилус = useRef<PenWatch | null>(null)
  const палец = useRef<FingerPan | null>(null)
  const холст = useRef<HTMLDivElement | null>(null)
  /** Есть ли ключи распознавания. Ссылкой: её читает перо из своего замыкания. */
  const распознаёт = useRef(false)
  распознаёт.current = session.data?.ready === true
  // Ответ о готовности целиком: из него перо берёт адрес моста и ключи-заглушки,
  // когда открывает живую сессию. Ссылкой по той же причине — перо живёт дольше
  // рендера, в котором его завели.
  const готовность = useRef<InkSession | null>(null)
  готовность.current = session.data ?? null

  const run = useBoardCheck(projectId, boardId, endpoint, версияЭкрана)

  const доска = (boards.data ?? []).find((д) => д.id === boardId)
  const имя = доска?.name || t('board.home.boardName', { n: доска?.n ?? 1 })

  /* ── сцена ───────────────────────────────────────────────────────────────── */

  useEffect(() => {
    if (!scene.data) return
    версия.current = scene.data.version
    setВерсияЭкрана(scene.data.version)
    // Распознанное берётся с тома **один раз**, при открытии доски: тот же ответ
    // приходит и на каждую запись сцены, а к тому времени в браузере словарь уже
    // новее — там могло прибавиться подтверждение, сделанное, пока запись шла.
    if (загружено.current) return
    загружено.current = true
    // Словарь с тома читается через `readCache`: доски, заведённые при
    // подтверждении строк, держат в нём состояния, которых больше нет.
    const пришедшее = readCache(scene.data.recognized)
    кэш.current = пришедшее
    setКэшЭкрана(пришедшее)
    // Росчерки с тома кладутся в модель сразу и строки собираются, не дожидаясь
    // первого `onChange` редактора: на открытой и не тронутой доске он может не
    // прийти вовсе, и чистовик стоял бы пустым, пока человек не коснётся холста.
    const сТома = (scene.data.scene?.elements ?? []) as readonly SceneElement[]
    if (сТома.length && элементы.current.length === 0) {
      элементы.current = [...сТома]
      тикнуть((н) => н + 1)
    }
  }, [scene.data])

  /**
   * Элементы и состояние вида приходят от редактора в его собственных типах, с
   * фирменными пометками на координатах. Доска читает у элемента ровно то, что
   * ей нужно (`scene.ts`), поэтому вход объявлен широко, а сужение стоит здесь —
   * в одном месте, а не в каждом обращении.
   */
  const приИзменении = useCallback((следующие: readonly unknown[], состояние: unknown) => {
    вид.current = состояние as ViewState & { viewBackgroundColor?: string }
    // Выделение читается здесь же: по нему сужается вложение к сообщению.
    // Версии элементов от выделения не меняются, поэтому оно узнаётся до
    // подписи сцены и своей подписью — иначе каждый кадр рождал бы новый Set.
    const отмечено = (состояние as { selectedElementIds?: Record<string, boolean> })
      .selectedElementIds
    const выбранныеId = Object.keys(отмечено ?? {})
      .filter((id) => отмечено?.[id])
      .sort()
    const подписьВыделения = выбранныеId.join(',')
    if (подписьВыделения !== подписьВыделенияБыла.current) {
      подписьВыделенияБыла.current = подписьВыделения
      setВыделение(new Set(выбранныеId))
    }
    if (!кадрВида.current) {
      кадрВида.current = requestAnimationFrame(() => {
        кадрВида.current = 0
        тикнутьВид((н) => н + 1)
      })
    }
    // Редактор зовёт `onChange` на каждом своём кадре — при прокрутке, движении
    // курсора, перерисовке, — а не только когда сцена изменилась. Таймеры
    // группировки, сохранения и паузы пера заводятся от изменения СЦЕНЫ, иначе
    // они сбрасывались бы каждый кадр и не срабатывали бы никогда. Изменение
    // сцены узнаётся по подписи из версий элементов: у редактора версия растёт
    // на каждую правку элемента, а удаление меняет пометку `isDeleted`.
    const список = следующие as readonly SceneElement[]
    let подпись = String(список.length)
    for (const э of список) {
      подпись += `,${(э as { version?: number }).version ?? 0}${э.isDeleted ? 'd' : ''}`
    }
    if (подпись === подписьСцены.current) return
    подписьСцены.current = подпись
    элементы.current = [...список]
    грязно.current = true
    if (кадр.current) return
    кадр.current = requestAnimationFrame(() => {
      кадр.current = 0
      тикнуть((н) => н + 1)
    })
  }, [])

  useEffect(
    () => () => {
      if (кадр.current) cancelAnimationFrame(кадр.current)
    },
    [],
  )

  /**
   * Ручка редактора — обязательно стабильная ссылка: редактор обёрнут в `memo`,
   * и новая стрелка в свойстве на каждый рендер ломает сравнение, после чего он
   * перерисовывается, снова зовёт `onChange` и просит новый кадр.
   */
  const приРучке = useCallback((апи: unknown) => {
    ручка.current = апи as BoardApi
    // Перо по умолчанию: доска заводилась под письмо от руки, и первый жест
    // человека на ней — написать, а не выделить. Через `setTimeout`, потому что
    // ручка выдаётся раньше, чем редактор доразберёт начальные данные, и
    // инструмент, поставленный прямо здесь, тут же затирается его собственным
    // восстановлением состояния.
    setTimeout(() => (апи as BoardApi).setActiveTool({ type: 'freedraw' }), 0)
  }, [])

  /** Положить новый словарь распознанного: и на экран, и в ближайшую запись. */
  const положитьКэш = useCallback((следующий: RecognizedCache) => {
    кэш.current = следующий
    setКэшЭкрана(следующий)
    // Распознанное уезжает на том вместе со сценой — значит, изменение словаря
    // делает доску такой же несохранённой, как новый росчерк.
    грязно.current = true
    тикнуть((н) => н + 1)
  }, [])

  /** Отложенное сохранение сцены. Пишем только то, что действительно менялось. */
  useEffect(() => {
    if (!грязно.current || !projectId || !boardId) return
    const таймер = setTimeout(() => {
      // Второй раз то же самое не пишем: сцену мог уже досохранить путь просьбы
      // к репетитору (`свести`), и вторая запись с прежней версией получила бы
      // от тома законный отказ «доску переписали», которого не было.
      if (!грязно.current) return
      грязно.current = false
      сохранитьСцену(
        {
          projectId,
          boardId,
          scene: sceneToJSON(элементы.current, вид.current),
          version: версия.current,
          recognized: кэш.current,
        },
        {
          onSuccess: (ответ) => {
            версия.current = ответ.version
            setВерсияЭкрана(ответ.version)
          },
          onError: (беда) => {
            // 409 — сцену изменила вторая вкладка или второе устройство. Молча
            // затирать чужую правку нельзя: доска теряется шумно, а не тихо.
            if (isApiError(беда) && беда.status === 409) setКонфликт(true)
          },
        },
      )
    }, ЗАДЕРЖКА_СОХРАНЕНИЯ)
    return () => clearTimeout(таймер)
    // `тик` здесь и есть сигнал «на холсте что-то изменилось».
  }, [тик, projectId, boardId, сохранитьСцену])

  // Начальные данные редактора — один объект на загрузку сцены, а не новый
  // литерал на каждый рендер: редактор сравнивает свойства и на новом объекте
  // обновляется сам, зовя `onChange`, — то есть каждый наш рендер порождал бы
  // ещё один его кадр, и так по кругу.
  //
  // Сцена приезжает с тома обычным JSON, а редактор объявляет для элементов
  // свои типы. Чинит и достраивает начальные данные он сам — другого описания
  // сцены, кроме его собственного, у нас нет, и проверять их здесь нечем.
  const начальныеДанные = useMemo(
    () => ({
      elements: (scene.data?.scene?.elements ?? []) as never,
      appState: {
        viewBackgroundColor: scene.data?.scene?.appState?.viewBackgroundColor ?? '#ffffff',
        currentItemStrokeWidth: 1,
      },
      scrollToContent: true,
    }),
    [scene.data],
  )

  /* ── строки сцены ────────────────────────────────────────────────────────── */

  /**
   * Пересборка росчерков в строки.
   *
   * Единственное место, где сцена превращается в строки, — и потому единственное
   * место, где меняются их отпечатки. Заодно из словаря распознанного выпадают
   * строки, которых на сцене больше нет: иначе запись стёртой строки уезжала бы
   * на том вечно.
   */
  useEffect(() => {
    const таймер = setTimeout(() => {
      const следующие = sceneLines(элементы.current)
      строки.current = следующие
      setСтрокиЭкрана(следующие)
      // Доска, заведённая до отдельного словаря, держит распознанное в разметке
      // своих росчерков. Вычитывается это ровно один раз — иначе открытие такой
      // доски стоило бы человеку запроса на каждую написанную строку.
      if (загружено.current && !перенесено.current && следующие.length) {
        перенесено.current = true
        if (Object.keys(кэш.current).length === 0) {
          const изРазметки = recognizedFromScene(элементы.current, следующие)
          if (Object.keys(изРазметки).length) {
            положитьКэш(изРазметки)
            return
          }
        }
      }
      // Из словаря выпадают стёртые строки, а у оставшихся обновляется место на
      // холсте: по нему служба выстраивает решение сверху вниз, если строки
      // отстали от сцены.
      const почищенный = syncPlaces(pruneRecognized(кэш.current, следующие), следующие)
      if (почищенный !== кэш.current) положитьКэш(почищенный)
    }, ЗАДЕРЖКА_ГРУПП)
    return () => clearTimeout(таймер)
  }, [тик, положитьКэш])

  /* ── распознавание ───────────────────────────────────────────────────────── */

  useEffect(() => {
    const перо_ = new InkPen({
      send: recognizeLines,
      session: () => готовность.current,
      elements: () => элементы.current,
      lines: () => строки.current,
      cache: () => кэш.current,
      onCache: положитьКэш,
      onState: (state, note) => setИнк({ state, note }),
      active: () => распознаёт.current,
    })
    перо.current = перо_
    return () => {
      перо_.stop()
      перо.current = null
    }
  }, [положитьКэш])

  /**
   * Любое изменение сцены заводит паузу заново. Пауза одна на все причины —
   * письмо, стирание, перенос: для распознавания они неразличимы, потому что
   * смотрит оно не на событие, а на отпечаток строки.
   */
  useEffect(() => {
    перо.current?.touch()
  }, [тик])

  useEffect(() => {
    стилус.current = new PenWatch()
    палец.current = new FingerPan({
      // Разводим перо с пальцем только там, где стилус уже видели: на планшете
      // без пера и на мыши палец обязан рисовать, как рисовал.
      enabled: () => стилус.current?.penSeen ?? false,
      view: () => вид.current,
      onView: ({ scrollX, scrollY, zoom }) =>
        ручка.current?.updateScene({
          appState: { scrollX, scrollY, zoom: { value: zoom } },
          captureUpdate: 'NEVER',
        }),
    })
    // Цепляемся к контейнеру, а не к `<canvas>`: холстов у редактора несколько
    // (статический, интерактивный, для нового элемента), и он их подменяет.
    // События указателя всплывают до контейнера в любом случае.
    стилус.current.attach(холст.current)
    палец.current.attach(холст.current)
    const стилус_ = стилус.current
    const палец_ = палец.current
    return () => {
      стилус_.detach()
      палец_.detach()
    }
  }, [])

  /* ── строки: правка руками и отправка ────────────────────────────────────── */

  /** Строки доски так, как их видят и панель, и призраки: одна модель на двоих. */
  const чистовик = useMemo(() => fairCopy(строкиЭкрана, кэшЭкрана), [строкиЭкрана, кэшЭкрана])

  /**
   * Строки из выделенного на холсте. Выделил росчерк — уезжает вся его строка:
   * строка и есть единица записи, половина формулы никому не нужна.
   */
  const выбранные = useMemo(
    () => (выделение.size ? чистовик.filter((с) => с.strokes.some((э) => выделение.has(э))) : []),
    [чистовик, выделение],
  )
  /** Что уедет с сообщением: выделенное, а без выделения — всё. */
  const приложено = выбранные.length ? выбранные : чистовик
  /** Ссылкой: отправка читает его из замыкания, которое старше рендера. */
  const приложеноСейчас = useRef<{ lines: FairLine[]; selected: boolean }>({
    lines: приложено,
    selected: выбранные.length > 0,
  })
  приложеноСейчас.current = { lines: приложено, selected: выбранные.length > 0 }

  useEffect(() => {
    const узел = страница.current
    const слушать = () => setВоВесьЭкран(document.fullscreenElement === узел && !!узел)
    document.addEventListener('fullscreenchange', слушать)
    return () => document.removeEventListener('fullscreenchange', слушать)
  }, [])

  const переключитьЭкран = useCallback(() => {
    const узел = страница.current
    if (!узел) return
    if (document.fullscreenElement) void document.exitFullscreen()
    else void узел.requestFullscreen?.()
  }, [])

  /**
   * Ручка ширины панели: тянется указателем, ширина считается от правого края
   * страницы. Пределы — не уже минимальной панели и не шире двух третей: холст
   * должен оставаться холстом.
   */
  const тянутьПанель = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const узел = страница.current
    if (!узел) return
    e.preventDefault()
    const край = узел.getBoundingClientRect().right
    const всего = узел.getBoundingClientRect().width
    const двигать = (ev: PointerEvent) => {
      const ширина = Math.round(край - ev.clientX)
      setШиринаПанели(Math.max(PANEL_MIN, Math.min(Math.round(всего * 0.66), ширина)))
    }
    const отпустить = () => {
      window.removeEventListener('pointermove', двигать)
      window.removeEventListener('pointerup', отпустить)
      setШиринаПанели((ш) => {
        writePanelWidth(ш)
        return ш
      })
    }
    window.addEventListener('pointermove', двигать)
    window.addEventListener('pointerup', отпустить)
  }, [])

  /**
   * Отправить строки службе.
   *
   * Строки уезжают **готовыми**: читает их сайт, и собрать их заново из сцены
   * служба может только по словарю распознанного, который едет рядом со сценой.
   * Зовётся это на правке руками — тогда, когда меняется именно то, что увидит
   * агент, а не то, что нарисовано, — и перед каждой просьбой к репетитору.
   */
  const отправитьСтроки = useCallback(() => {
    if (!projectId || !boardId) return
    пересобрать({ projectId, boardId, lines: строки.current, recognized: кэш.current })
  }, [projectId, boardId, пересобрать])

  const начатьПравку = useCallback((id: string, где: 'ghost' | 'list') => {
    setПравка({ id, latex: кэш.current[id]?.latex ?? '', where: где })
  }, [])

  /**
   * Записать набранное руками.
   *
   * Дальше распознаватель эту строку не трогает: человек уже сказал, что здесь
   * написано, и перебивать его новой догадкой значило бы терять его правку
   * каждый раз, когда он дорисует в строке запятую.
   */
  const записатьПравку = useCallback(() => {
    if (!правка) return
    const строка = строки.current.find((с) => с.id === правка.id)
    if (строка) положитьКэш(typeLine(кэш.current, строка, правка.latex, now()))
    setПравка(null)
    отправитьСтроки()
  }, [правка, положитьКэш, отправитьСтроки])

  /* ── ответ репетитора ────────────────────────────────────────────────────── */

  /**
   * Свести доску на том: сцена со словарём, затем строки решения.
   *
   * По очереди и с ожиданием, а не отложенной записью: строки собираются по
   * сцене, и если они уедут раньше неё, служба увидит решение по записи, которой
   * ещё нет. Возвращается версия сцены, по которой строки собраны, — с ней и
   * уходит просьба.
   */
  const свести = useCallback(async (): Promise<number> => {
    if (!projectId || !boardId) return версия.current
    if (грязно.current) {
      грязно.current = false
      const ответ = await сохранитьСценуЖдя({
        projectId,
        boardId,
        scene: sceneToJSON(элементы.current, вид.current),
        version: версия.current,
        recognized: кэш.current,
      })
      версия.current = ответ.version
      setВерсияЭкрана(ответ.version)
    }
    await пересобратьЖдя({
      projectId,
      boardId,
      lines: строки.current,
      recognized: кэш.current,
    })
    return версия.current
  }, [projectId, boardId, сохранитьСценуЖдя, пересобратьЖдя])

  /** Последнее сообщение человека: его же повторяет автоматический повтор. */
  const просьба = useRef<string | null>(null)
  /** Повтор на «доска изменилась» бывает ровно один — иначе это круг. */
  const повторено = useRef(false)

  /**
   * Написать репетитору.
   *
   * Перед отправкой доска **сводится сама**: сцена и строки уезжают на том, и
   * задание уходит с той версией сцены, по которой строки только что собраны.
   * Иначе служба справедливо отказывала бы «строки собраны по прежней записи» —
   * и человек, ничего дурного не сделавший, читал бы отказ вместо ответа.
   */
  const начать = useCallback(
    async (text: string, повтор = false) => {
      просьба.current = text
      if (!повтор) повторено.current = false
      let версияСцены = версия.current
      try {
        версияСцены = await свести()
      } catch (беда) {
        // 409 — сцену изменила вторая вкладка. Писать по чужой записи нельзя:
        // ответ пришёл бы про чужое решение.
        if (isApiError(беда) && беда.status === 409) setКонфликт(true)
        return
      }
      // Вложение — ровно то, что уехало: строки, у которых есть текст, и только
      // из выделенного, если на холсте что-то выделено. Строка, которую не
      // прочитал никто, агенту не уезжает, и показывать её во вложении
      // отправленного сообщения значило бы обещать больше, чем послано.
      const { lines: приложенные, selected } = приложеноСейчас.current
      const строкиСообщения = приложенные.filter((с) => !!с.latex.trim())
      run.ask({
        mode: 'chat',
        sceneVersion: версияСцены,
        message: text,
        lines: selected ? строкиСообщения.map((с) => с.step) : undefined,
      })
      // Повтор — то же сообщение, а не новое: оно остаётся одним и снова ждёт.
      if (!повтор) setОжидание({ text, lines: строкиСообщения, sceneVersion: версияСцены })
    },
    [run, свести],
  )

  const отправить = useCallback((text: string) => void начать(text), [начать])

  /** Ответ записан на том и перечитан — ждать больше нечего. */
  useEffect(() => {
    if (!run.running && run.result) setОжидание(null)
  }, [run.running, run.result])

  /**
   * «Доска изменилась» — повторить просьбу один раз, не спрашивая человека.
   *
   * Отказ означает, что между сведением и стартом прогона доску успели тронуть:
   * дорисовали росчерк, дочитали строку. Второй заход той же цепочкой снимает
   * это почти всегда; если не снял — человек видит слова и кнопку, и уже сам
   * решает, что делать.
   */
  useEffect(() => {
    if (run.errorCode !== SCENE_STALE || повторено.current || !просьба.current) return
    повторено.current = true
    void начать(просьба.current, true)
  }, [run.errorCode, начать])

  /* ── выноски и подсветка ─────────────────────────────────────────────────── */

  const наложения = useMemo(() => {
    const список: { key: string; rect: Rect; tone: string }[] = []
    if (подсветка?.length) {
      const рамка = highlightRect(подсветка, элементы.current, вид.current)
      if (рамка && inView(рамка, вид.current)) {
        список.push({ key: 'hover', rect: рамка, tone: 'accent' })
      }
    }
    return список
    // `тик` в списке зависимостей стоит **намеренно**, и линтер о нём не знает:
    // выноски считаются по `элементы.current` и `вид.current`, то есть по
    // ссылкам, за которыми линтер не следит. Прокрутка и масштаб живут в
    // состоянии вида, и выноска, посчитанная один раз, отклеилась бы от
    // росчерка на первом же сдвиге холста.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [подсветка, тик])

  /* ── отрисовка ───────────────────────────────────────────────────────────── */

  if (scene.isError) {
    return <ErrorState error={scene.error} onRetry={() => void scene.refetch()} />
  }

  const цена = usage.data?.prices?.[BOARD_CHECK] ?? null
  // На рейке свёрнутой панели стои́т число строк, которых никто не прочитал: это
  // единственное, что человеку стоит знать о панели, пока она свёрнута.
  const неразобранных = чистовик.length - willSee(чистовик)

  return (
    <div
      ref={страница}
      className="flex h-[calc(100dvh-7rem)] min-h-[480px] flex-col gap-s2 [&:fullscreen]:h-dvh [&:fullscreen]:bg-surface [&:fullscreen]:p-s2"
    >
      <div className="flex items-center gap-s2">
        {/* Назад — к списку досок пространства, а не к работе: работу человек
            не выбирал, и называть её здесь значило бы показать ему папку,
            которой он не заводил. */}
        <Button variant="ghost" size="sm" onClick={() => navigate('/board')}>
          <Icon name="arrowLeft" size={16} />
          {t('board.home.title')}
        </Button>
        <div className="ml-auto flex items-center gap-s2">
          {свёрнута && (
            <Button variant="secondary" size="sm" onClick={() => setСвёрнута(false)}>
              <Icon name="panelOpen" size={16} />
              {t('board.board.panelShow')}
              {неразобранных > 0 && (
                <span className="rounded-full bg-warn-bg px-1.5 text-xs text-warn">
                  {неразобранных}
                </span>
              )}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            iconOnly
            aria-label={воВесьЭкран ? t('board.board.fullscreenExit') : t('board.board.fullscreen')}
            title={воВесьЭкран ? t('board.board.fullscreenExit') : t('board.board.fullscreen')}
            onClick={переключитьЭкран}
          >
            <Icon name={воВесьЭкран ? 'shrink' : 'expand'} size={16} />
          </Button>
        </div>
      </div>

      {конфликт && (
        <p className="rounded-sm border border-warn bg-warn-bg px-s2 py-1.5 text-sm text-warn">
          {t('board.board.conflict')}{' '}
          <button type="button" className="underline" onClick={() => void scene.refetch()}>
            {t('board.board.reload')}
          </button>
        </p>
      )}
      {saveScene.isError && !конфликт && (
        <p className="text-xs text-err">{errorText(saveScene.error)}</p>
      )}

      <div
        className={cn(
          'grid min-h-0 flex-1 overflow-hidden rounded-md border border-line',
          // Ширина панели — переменная, за которую тянут ручкой; на узком
          // экране колонка одна, и панель ложится под холст.
          свёрнута ? 'grid-cols-1' : 'grid-cols-1 lg:grid-cols-[minmax(0,1fr)_var(--panel)]',
        )}
        style={{ '--panel': `${ширинаПанели}px` } as React.CSSProperties}
      >
        <div ref={холст} className="relative min-h-0 bg-[var(--card-front)]">
          {/* Оба наложения стоят в дереве ПЕРЕД редактором, и это единственное,
              чем они держатся между его полотнами и его островками UI. У
              полотен `z-index` 1 и 2, у слоя островков — 4, своего контекста
              наложения контейнер редактора не создаёт; значит при равном
              `z-index` 4 порядок решает дерево: кто раньше — тот ниже. Отсюда
              формула под строкой видна поверх непрозрачного полотна и уходит
              под нижнюю панель, меню и зум, а не накрывает их. */}
          <Ghosts
            lines={чистовик}
            view={вид.current}
            editing={правка}
            onEdit={(id) => начатьПравку(id, 'ghost')}
            onEditChange={(latex) => setПравка((было) => (было ? { ...было, latex } : было))}
            onEditSave={записатьПравку}
            onEditCancel={() => setПравка(null)}
            onHover={setПодсветка}
          />

          {/* Выноски — наложением над холстом. Событий не ловят: под ними
              продолжают писать. */}
          <div className="pointer-events-none absolute inset-0 z-[4] overflow-hidden">
            {наложения.map((н) => (
              <span
                key={н.key}
                data-tone={н.tone}
                className={cn(
                  'absolute rounded-sm border-2',
                  н.tone === 'ok' && 'border-ok bg-ok-bg',
                  н.tone === 'err' && 'border-err bg-err-bg',
                  н.tone === 'warn' && 'border-warn bg-warn-bg',
                  н.tone === 'info' && 'border-info bg-info-bg',
                  н.tone === 'accent' && 'border-accent bg-accent-bg',
                  run.stale && 'opacity-40',
                )}
                style={{
                  left: н.rect.x - 6,
                  top: н.rect.y - 6,
                  width: н.rect.width + 12,
                  height: н.rect.height + 12,
                }}
              />
            ))}
          </div>

          {чистовик.length === 0 && (
            <p className="pointer-events-none absolute inset-x-0 top-1/2 z-[4] text-center text-sm text-muted">
              {t('board.board.emptyCanvas')}
            </p>
          )}

          <Suspense fallback={<SkeletonLines count={6} className="p-s4" />}>
            {scene.isPending ? (
              <SkeletonLines count={6} className="p-s4" />
            ) : (
              <Excalidraw
                excalidrawAPI={приРучке}
                onChange={приИзменении}
                theme={appearance.mode === 'dark' ? 'dark' : 'light'}
                langCode="ru-RU"
                initialData={начальныеДанные}
                UIOptions={ПАРАМЕТРЫ_РЕДАКТОРА}
              />
            )}
          </Suspense>
        </div>

        {!свёрнута && (
          <div className="relative min-h-0">
            {/* Ручка ширины: узкая полоса по левому краю панели, только на
                широком экране — на узком колонка одна и тянуть нечего. */}
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label={t('board.board.resize')}
              className="absolute inset-y-0 left-0 z-[5] hidden w-2 -translate-x-1/2 cursor-col-resize hover:bg-accent-bg lg:block"
              onPointerDown={тянутьПанель}
            />
            <TutorPanel
              name={имя}
              task={task.data?.text ?? ''}
              onTask={(текст) => setTask.mutate({ projectId, boardId, text: текст })}
              ink={{ state: инк.state, note: инк.note, reason: session.data?.reason ?? '' }}
              inkOpens={session.data?.opens_this_month ?? null}
              lines={чистовик}
              attached={приложено}
              selected={выбранные.length > 0}
              editing={правка}
              onEdit={(id) => начатьПравку(id, 'list')}
              onEditChange={(latex) => setПравка((было) => (было ? { ...было, latex } : было))}
              onEditSave={записатьПравку}
              onEditCancel={() => setПравка(null)}
              onHover={setПодсветка}
              messages={chat.data?.messages ?? []}
              pending={ожидание}
              run={run}
              price={цена}
              canAsk={!!endpoint}
              onSend={отправить}
              onRebuild={отправитьСтроки}
              onCollapse={() => setСвёрнута(true)}
            />
          </div>
        )}
      </div>
    </div>
  )
}
