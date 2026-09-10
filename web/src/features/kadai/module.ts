/**
 * module — под каким модулем открыт сценарий заданий: слова и адреса.
 *
 * Экраны сценария (`KadaiWorkPage`, `KadaiNewRunPage`) стоят в двух модулях
 * сразу. В «Решениях» прогон называется решением и кончается архивом; в
 * «Отчётах» тот же прогон — **отчёт из задания**: кончается он собранным
 * документом, а из готовых блоков делается бланк с тегами. Носитель у обоих
 * один, маршруты службы те же, и различаются модули ровно тремя вещами:
 * словами, адресами и тем, до какой стадии идёт прогон.
 *
 * Поэтому здесь не второй набор экранов, а описание модуля, которое экраны
 * получают пропом. Копия страниц под «Отчёты» разъехалась бы с оригиналом на
 * первой же правке сценария — и разъехалась бы молча, потому что обе половины
 * продолжали бы работать.
 *
 * Слова названы **ключами перевода**, а не текстом: тексты живут в `i18n/ru`, и
 * второе их место здесь означало бы строку продукта, спрятанную в коде.
 */

/** Ключи перевода бланка с тегами; модуль без бланка их не задаёт. */
export type KadaiTemplateWords = {
  /** Кнопка «сделать бланк». */
  make: string
  /** Строка о том, что такое бланк и откуда он берётся. */
  hint: string
  /** Заголовок тоста об удаче. */
  toast: string
  /** Строка о готовом бланке, `{name}` — его имя на полке. */
  done: string
  /** Ссылка на сам файл. */
  download: string
  /** Ссылка на полку бланков. */
  shelf: string
}

export type KadaiScope = {
  /** Список прогонов модуля: туда ведёт кнопка возврата. */
  list: (projectId: string) => string
  /** Экран одного прогона: туда уходит форма заведения. */
  run: (projectId: string, runId: string) => string
  /**
   * Стадии, которых в этом модуле нет.
   *
   * Порядок стадий задаёт служба, и модуль не может убрать стадию из сценария —
   * но может не обещать её человеку. В «Отчётах» прогон останавливается на
   * сборке, и «Архив» в полоске шагов вечно оставался бы ждущим: полоска
   * говорила бы, что работа не доделана, при том что она готова.
   */
  skip: readonly string[]
  /** До какой стадии идёт прогон «до конца». `null` — до последней. */
  until: string | null
  /** Бланк с тегами из блоков; `null` — в этом модуле его не делают. */
  template: KadaiTemplateWords | null
  /** Слова: экран один, а называется в модулях по-разному. */
  words: {
    /** Имя безымянного прогона, `{n}` — его номер. */
    runName: string
    /** Кнопка возврата к списку. */
    toList: string
    /** Заголовок формы заведения. */
    newTitle: string
    /** Кнопка формы заведения. */
    newSubmit: string
    /** Подпись поля имени. */
    newName: string
    /** Подсказка под полем имени. */
    newNameHint: string
    /** Заголовок части формы, куда кладут задание. */
    newCondition: string
    /** Подпись поля пожеланий. */
    newWishes: string
    /** Подсказка под пожеланиями. */
    newWishesHint: string
    /** Пример в поле пожеланий. */
    newWishesPlaceholder: string
    /** Первый пуск. */
    start: string
    /** Повторный пуск. */
    again: string
    /** Строка об остановленном прогоне: она называет кнопку продолжения. */
    stopped: string
  }
}

/** «Решения»: прогон целиком, вплоть до архива. */
export const РЕШЕНИЕ: KadaiScope = {
  list: (projectId) => `/kadai/${projectId}`,
  run: (projectId, runId) => `/kadai/${projectId}/${runId}`,
  skip: [],
  until: null,
  template: null,
  words: {
    runName: 'kadai.home.runName',
    toList: 'kadai.work.toList',
    newTitle: 'kadai.new.title',
    newSubmit: 'kadai.new.submit',
    newName: 'kadai.new.name',
    newNameHint: 'kadai.new.nameHint',
    newCondition: 'kadai.new.condition',
    newWishes: 'kadai.new.wishes',
    newWishesHint: 'kadai.new.wishesHint',
    newWishesPlaceholder: 'kadai.new.wishesPlaceholder',
    start: 'kadai.run.start',
    again: 'kadai.run.again',
    stopped: 'kadai.run.stopped',
  },
}

/**
 * «Отчёты»: тот же прогон, но на выходе документ и бланк, а не архив.
 *
 * Возврат ведёт в ленту отчётов, суженную до этой работы: своей страницы
 * «решения работы» у модуля нет, и лента — то место, откуда сюда пришли.
 */
export const ОТЧЁТ_ИЗ_ЗАДАНИЯ: KadaiScope = {
  list: (projectId) => `/reports?project=${encodeURIComponent(projectId)}`,
  run: (projectId, runId) => `/reports/${projectId}/live/${runId}`,
  skip: ['архив'],
  until: 'сборка',
  template: {
    make: 'reports.live.template.make',
    hint: 'reports.live.template.hint',
    toast: 'reports.live.template.toast',
    done: 'reports.live.template.done',
    download: 'reports.live.template.download',
    shelf: 'reports.live.template.shelf',
  },
  words: {
    runName: 'reports.live.runName',
    toList: 'reports.live.toList',
    newTitle: 'reports.live.newTitle',
    newSubmit: 'reports.live.newSubmit',
    newName: 'reports.live.newName',
    newNameHint: 'reports.live.newNameHint',
    newCondition: 'reports.live.newCondition',
    newWishes: 'reports.live.newWishes',
    newWishesHint: 'reports.live.newWishesHint',
    newWishesPlaceholder: 'reports.live.newWishesPlaceholder',
    start: 'reports.live.start',
    again: 'reports.live.again',
    stopped: 'reports.live.stopped',
  },
}
