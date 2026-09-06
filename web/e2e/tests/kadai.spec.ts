/**
 * Задания (kadai) браузером: условие текстом → семь стадий → блоки → замечание
 * → версии → «как будет в Word».
 *
 * Что этим проверяется и чего не проверяет ни модульная проверка, ни `smoke.sh`:
 * склейка страницы с очередью. Прогон `kadai_run` идёт через настоящий воркер в
 * подпроцессе, ход стадий приезжает событиями SSE, а собранный PDF —
 * артефактом, который показывается `<embed>`'ом по прямому адресу с `?inline=1`.
 * Ломается это ровно на стыках, и увидеть их можно только браузером.
 *
 * Модель поддельная (`e2e/fake-llm`), поэтому строение работы выходит из одного
 * раздела: схема ответа просит `minItems: 1`, а придумывать больше подделке
 * нечем. Проверяется путь, а не содержание работы.
 */
import { expect, test } from '@playwright/test'

import { signUpAndLogin, t } from './helpers'

const УСЛОВИЕ =
  'Задача 1. Написать на Python программу, считающую сумму чисел от 1 до n. ' +
  'Построить блок-схему алгоритма и оформить отчёт.'

// Состояния стадии — значения службы (`kadai.stages`), они же в `data-state`.
const СДЕЛАНО = 'сделано'
const СПОТКНУЛАСЬ = 'споткнулась'

test('задание: условие текстом, прогон до архива, замечание, версии, PDF', async ({ page }) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'kadai')

  // ── список модуля и заведение работы ───────────────────────────────────────
  // Пункт сайдбара, а не плитка модуля на дашборде: имя у них одно.
  await page.getByRole('link', { name: t('shell.nav.kadai'), exact: true }).click()
  await expect(page.getByRole('heading', { name: t('kadai.home.title') })).toBeVisible()

  // Работа и решение заводятся по очереди: работа держит материалы и потолок
  // расхода, а решений в ней столько, сколько задач задали.
  await page
    .getByRole('button', { name: t('kadai.home.newWork') })
    .first()
    .click()
  await page.getByLabel(t('kadai.new.workName')).fill('Сумма ряда')
  await page.getByRole('button', { name: t('kadai.home.newWorkSubmit'), exact: true }).click()
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/new$/)
  await page.getByRole('radio', { name: t('kadai.new.byText') }).check()
  await page.getByLabel(t('kadai.new.textLabel')).fill(УСЛОВИЕ)
  await page.getByRole('button', { name: t('kadai.new.submit'), exact: true }).click()

  // ── шаг «условие распознано» ───────────────────────────────────────────────
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/)
  await expect(page.getByText(t('kadai.condition.title'))).toBeVisible()
  // Текст условия приезжает разбором материала, а не прогоном: он уже здесь.
  await expect(page.getByText('сумму чисел от 1 до n', { exact: false })).toBeVisible({
    timeout: 30_000,
  })
  // Пока условие не подтверждено, решать нельзя — в этом и весь смысл шага.
  const решить = page.getByRole('button', { name: t('kadai.run.start') })
  await expect(решить).toBeDisabled()

  // ── «поправить»: правка ложится новым материалом и становится условием ─────
  await page.getByRole('button', { name: t('kadai.condition.fix') }).click()
  await page
    .getByLabel(t('kadai.condition.title'))
    .fill(`${УСЛОВИЕ} Учесть, что n целое и положительное.`)
  await page.getByRole('button', { name: t('kadai.condition.save') }).click()
  await expect(page.getByText('n целое и положительное', { exact: false })).toBeVisible({
    timeout: 60_000,
  })

  // Перезагрузка: подтверждение — состояние экрана, а условие — состояние
  // проекта, и после возврата спросить «всё верно?» надо снова.
  await page.reload()
  await expect(решить).toBeDisabled()
  await page.getByRole('button', { name: t('kadai.condition.ok') }).click()
  await expect(решить).toBeEnabled()

  // ── прогон: семь стадий по потоку ──────────────────────────────────────────
  await решить.click()
  // Последняя стадия помечена сделанной — значит доехали и события, и снимок.
  await expect(page.locator(`[data-stage="архив"][data-state="${СДЕЛАНО}"]`)).toBeVisible({
    timeout: 150_000,
  })

  // ── архив стадии «архив» скачивается со страницы ──────────────────────────
  // ZIP кладётся артефактом задания, а не в `out/` на томе: раньше скачать его
  // со страницы было нечем, и человек про архив только читал.
  const архив = page.getByRole('link', { name: t('kadai.archive.download') })
  await expect(архив).toBeVisible({ timeout: 30_000 })
  await expect(архив).toHaveAttribute('href', /\/api\/projects\/.+\/artifacts\/.+/)
  const [зип] = await Promise.all([page.waitForEvent('download'), архив.click()])
  expect(await зип.failure()).toBeNull()
  expect(зип.suggestedFilename()).toMatch(/\.zip$/)

  // ── блоки видны карточками, с меткой источника ─────────────────────────────
  const блоки = page.locator('article')
  await expect.poll(() => блоки.count(), { timeout: 30_000 }).toBeGreaterThan(0)
  await expect(блоки.first().getByText(t('kadai.blocks.byAgent'))).toBeVisible()

  // ── версии списка до замечания ─────────────────────────────────────────────
  await page.getByRole('radio', { name: t('kadai.tabs.versions') }).click()
  // Список версий у задания и у тега — один и тот же компонент
  // (`reports/VersionHistory`), и строка в нём узнаётся по отметке сравнения.
  const версии = page.locator('li:has(input[type="checkbox"])')
  // Список приезжает своим запросом, и вкладку только что открыли: считать
  // сразу — значит считать пустоту, которой ещё не успели заполниться.
  await expect.poll(() => версии.count(), { timeout: 30_000 }).toBeGreaterThan(0)
  const было = await версии.count()

  // ── замечание к блоку → kadai_rework ───────────────────────────────────────
  await блоки.first().getByRole('button').first().click()
  await page.getByLabel(t('kadai.blocks.note')).fill('перепиши короче')
  await page.getByRole('button', { name: t('kadai.blocks.redo') }).click()
  await expect.poll(() => версии.count(), { timeout: 150_000 }).toBeGreaterThan(было)
  await expect(
    page.getByRole('button', { name: t('reports.versions.rollback') }).first(),
  ).toBeVisible()

  // ── «как будет в Word»: PDF во встроенном просмотрщике ─────────────────────
  await page.getByRole('radio', { name: t('kadai.tabs.preview') }).click()
  const превью = page.locator('embed[type="application/pdf"]')
  await expect(превью).toBeVisible({ timeout: 60_000 })
  await expect(превью).toHaveAttribute('src', /\/api\/projects\/.+\/artifacts\/.+\?inline=1$/)

  // ── и сам документ скачивается ────────────────────────────────────────────
  // Отдельно от превью: показ и скачивание — это один адрес с параметром и без
  // него, и перепутать их нельзя ни в ту, ни в другую сторону.
  const word = page.getByRole('link', { name: t('reports.pdf.downloadDocx') })
  await expect(word).toHaveAttribute('href', /\/api\/projects\/.+\/artifacts\/.+/)
  const [файл] = await Promise.all([page.waitForEvent('download'), word.click()])
  expect(await файл.failure()).toBeNull()
  expect(файл.suggestedFilename()).toMatch(/\.docx$/)
})

/**
 * Вставшая работа: платный обход закрыт, чинит её «начать заново».
 *
 * Раньше вставшую работу нельзя было сдвинуть ничем, кроме замечания к
 * условию, — а оно переигрывает всё с разбора задания и стоит
 * денег. Теперь стадия возвращается в ход даром (`POST …/kadai/restart`: ни
 * одного вызова модели), и прогон с неё ставит человек тем же нажатием.
 *
 * Работа роняется маркером `[[FAKE:500]]` в тексте условия: он уезжает в модель
 * тем же путём, что и настоящее условие, и стадия «разбор задания» спотыкается
 * на первом же вызове.
 *
 * Что проверяется наблюдаемым, а не догадкой: (1) споткнувшаяся стадия видна;
 * (2) обычная кнопка прогона выключена — второе нажатие стоило бы цены задания
 * и не сделало бы ничего; (3) «начать заново» ставит НОВЫЙ прогон, и это видно
 * по колокольчику: упавших заданий становится два вместо одного. Колокольчик
 * взят намеренно — счётчик там растёт и не убывает, поэтому проверка не
 * зависит от того, успели ли мы застать работу «в ходу».
 */
test('вставшая работа: повторный прогон закрыт, «начать заново» ставит новый', async ({ page }) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'kadai-restart')

  await page.goto('/kadai')
  // Работа и решение заводятся по очереди: работа держит материалы и потолок
  // расхода, а решений в ней столько, сколько задач задали.
  await page
    .getByRole('button', { name: t('kadai.home.newWork') })
    .first()
    .click()
  await page.getByLabel(t('kadai.new.workName')).fill('Работа, которая встанет')
  await page.getByRole('button', { name: t('kadai.home.newWorkSubmit'), exact: true }).click()
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/new$/)
  await page.getByRole('radio', { name: t('kadai.new.byText') }).check()
  await page.getByLabel(t('kadai.new.textLabel')).fill(`${УСЛОВИЕ} [[FAKE:500]]`)
  await page.getByRole('button', { name: t('kadai.new.submit'), exact: true }).click()
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/)

  await expect(page.getByText('сумму чисел от 1 до n', { exact: false })).toBeVisible({
    timeout: 30_000,
  })
  await page.getByRole('button', { name: t('kadai.condition.ok') }).click()
  const решить = page.getByRole('button', { name: t('kadai.run.start') })
  await expect(решить).toBeEnabled()
  await решить.click()

  // ── работа встала на разборе задания ──────────────────────────────────────
  await expect(
    page.locator(`[data-stage="разбор задания"][data-state="${СПОТКНУЛАСЬ}"]`),
  ).toBeVisible({ timeout: 150_000 })
  await expect(page.getByText(t('kadai.run.restartHint'))).toBeVisible()

  // Повторный прогон вставшую работу не чинит, и кнопка это знает.
  await expect(page.getByRole('button', { name: t('kadai.run.again') })).toBeDisabled()

  // ── сколько упавших заданий уже пришло ────────────────────────────────────
  /** Упавшие задания в колокольчике. Растёт и не убывает. */
  async function упавших(): Promise<number> {
    await page.getByRole('button', { name: t('shell.notifications.label') }).click()
    const список = page.getByRole('menu')
    await expect(список).toBeVisible()
    const n = await список
      .getByRole('menuitem')
      .filter({ hasText: t('notifications.jobFailed') })
      .count()
    await page.keyboard.press('Escape')
    await expect(список).toHaveCount(0)
    return n
  }
  await expect.poll(упавших, { timeout: 60_000 }).toBe(1)

  // ── «начать заново»: сброс даром и новый прогон одним нажатием ────────────
  await page.getByRole('button', { name: t('kadai.run.restart') }).click()
  // Второе упавшее задание могло взяться только из этого нажатия: обычная
  // кнопка прогона выключена, а других путей поставить `kadai_run` на экране
  // нет.
  await expect.poll(упавших, { timeout: 150_000 }).toBe(2)

  // Стадия, с которой начали заново, снова споткнулась — и это правда:
  // условие с маркером осталось тем же, «начать заново» его не переписывает.
  await expect(
    page.locator(`[data-stage="разбор задания"][data-state="${СПОТКНУЛАСЬ}"]`),
  ).toBeVisible({ timeout: 30_000 })
})
