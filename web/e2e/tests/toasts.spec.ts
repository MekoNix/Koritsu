/**
 * Упавшее задание показывается одним тостом, а не двумя.
 *
 * Раньше провал прогона тостили двое: оболочка (`useUserEvents`, по
 * событию `job_failed`) и сама область (`features/reports/useFill`, по концу
 * потока задания). Человек получал две карточки об одной беде, и это было видно
 * только глазами — ни один модульный тест такого не ловит, потому что каждый из
 * двух тостов сам по себе правильный.
 *
 * Проверка смотрит не «есть ли тост», а сколько их было ОДНОВРЕМЕННО за всё
 * время жизни: считаем наибольшее число видимых тостов от появления первого до
 * того, как он уйдёт сам (шесть секунд, `ui/toast.tsx`).
 *
 * Задание роняется маркером `[[FAKE:500]]` в соседнем теге — тем же способом,
 * что и в `smoke.sh`: другого пути передать маркер модели с сайта нет.
 */
import { expect, test } from '@playwright/test'

import { TAG_ONE, TAG_TWO, signUpAndLogin, t, templateDocx } from './helpers'

const ПРОЕКТ = 'Проверка тостов'

test('упавшее задание — один тост, и он называет причину', async ({ page }) => {
  await signUpAndLogin(page, 'toast')

  // Проект с шаблоном: нужны два тега — один роняем, соседним передаём маркер.
  await page.goto('/projects')
  await page
    .getByRole('button', { name: t('projects.list.create') })
    .first()
    .click()
  const окно = page.getByRole('dialog')
  await окно.getByLabel(t('projects.create.name')).fill(ПРОЕКТ)
  await окно.locator('input[type="file"]').setInputFiles(templateDocx())
  await окно.getByRole('button', { name: t('common.action.create') }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/)
  const projectId = (page.url().match(/projects\/([0-9a-f-]{36})/) as RegExpMatchArray)[1] as string

  await page.goto(`/reports/${projectId}`)

  // Маркер — значением соседнего тега: оттуда он уедет в промпт прогона.
  await page.getByRole('button', { name: new RegExp(`\\{\\{${TAG_TWO}\\}\\}`) }).click()
  const второе = page.getByRole('textbox', { name: t('reports.editor.field', { tag: TAG_TWO }) })
  await второе.fill('[[FAKE:500]]')
  await page.getByRole('button', { name: t('common.action.save'), exact: true }).click()
  await expect(page.getByText(t('reports.editor.byHand', { n: 1 }))).toBeVisible()

  await page.getByRole('button', { name: new RegExp(`\\{\\{${TAG_ONE}\\}\\}`) }).click()
  await page.getByRole('button', { name: t('reports.editor.generate'), exact: true }).click()

  const тосты = page.getByRole('status')
  let наибольшее = 0
  const посчитать = async () => {
    const сейчас = await тосты.count()
    наибольшее = Math.max(наибольшее, сейчас)
    return сейчас
  }

  // Ждём тоста о провале.
  await expect.poll(посчитать, { timeout: 120_000, intervals: [200] }).toBeGreaterThan(0)
  await expect(тосты.first()).toContainText(t('notifications.jobFailed'))
  // Причина — по коду службы (`run_failed`), а не английским текстом.
  await expect(тосты.first()).toContainText(t('errors.run_failed'))

  // …и досматриваем до конца его жизни: второй тост, приехавший следом,
  // попал бы в это же окно наблюдения.
  await expect.poll(посчитать, { timeout: 30_000, intervals: [200] }).toBe(0)
  expect(наибольшее).toBe(1)
})
