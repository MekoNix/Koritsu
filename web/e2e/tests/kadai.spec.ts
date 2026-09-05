/**
 * Задания (kadai) браузером: условие текстом → семь стадий → блоки → замечание
 * → версии → «как будет в Word».
 *
 * Что этим проверяется и чего не проверяет ни модульная проверка, ни `smoke.sh`:
 * склейка страницы с очередью. Прогон `kadai_run` идёт через настоящий воркер в
 * подпроцессе, ход стадий приезжает событиями SSE, а собранный PDF —
 * артефактом, который надо вычитать `fetch`'ем и показать `<embed>`'ом.
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

test('задание: условие текстом, прогон до архива, замечание, версии, PDF', async ({ page }) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'kadai')

  // ── список модуля и заведение работы ───────────────────────────────────────
  // Пункт сайдбара, а не плитка модуля на дашборде: имя у них одно.
  await page.getByRole('link', { name: t('shell.nav.kadai'), exact: true }).click()
  await expect(page.getByRole('heading', { name: t('kadai.home.title') })).toBeVisible()

  // Кнопок «завести» две — в шапке и в пустом состоянии; делают они одно.
  await page
    .getByRole('button', { name: t('kadai.home.create') })
    .first()
    .click()
  await page.getByLabel(t('kadai.new.name')).fill('Сумма ряда')
  await page.getByRole('radio', { name: t('kadai.new.byText') }).check()
  await page.getByLabel(t('kadai.new.textLabel')).fill(УСЛОВИЕ)
  await page.getByRole('button', { name: t('kadai.new.submit'), exact: true }).click()

  // ── шаг «условие распознано» ───────────────────────────────────────────────
  await expect(page).toHaveURL(/\/kadai\/[0-9a-f-]{36}$/)
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
  await expect(page.locator('embed[type="application/pdf"]')).toBeVisible({ timeout: 60_000 })

  // ── и сам документ скачивается ────────────────────────────────────────────
  // Отдельно от превью: `<embed>` показывает PDF через `blob:` (служба отдаёт
  // артефакт с `Content-Disposition: attachment`), а ссылка ведёт на настоящий
  // адрес артефакта, и по ней должен приезжать файл, а не отказ.
  const word = page.getByRole('link', { name: t('reports.pdf.downloadDocx') })
  await expect(word).toHaveAttribute('href', /\/api\/projects\/.+\/artifacts\/.+/)
  const [файл] = await Promise.all([page.waitForEvent('download'), word.click()])
  expect(await файл.failure()).toBeNull()
  expect(файл.suggestedFilename()).toMatch(/\.docx$/)
})
