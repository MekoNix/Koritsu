/**
 * Доска браузером: заведение одним нажатием, письмо по холсту, строка, набранная
 * руками, и прогон проверки через настоящую очередь.
 *
 * Что этим проверяется и чего не проверяет ни модульная проверка, ни `smoke.sh`:
 * склейка страницы с носителем и с очередью. Росчерк ложится в сцену редактора,
 * страница собирает из сцены строку, строки уезжают на том готовыми, задание
 * `board_check` идёт через настоящий воркер в подпроцессе, а вердикт приезжает
 * событиями SSE. Ломается это ровно на стыках, и увидеть их можно только
 * браузером.
 *
 * **В MyScript проверка не ходит ни при каких обстоятельствах**: каждый вызов
 * распознавателя оплачен. Ключей на стенде нет, поэтому доска здесь живёт в
 * состоянии «распознавание выключено» — законном и своём: рисовать, сохранять и
 * проверять набранные руками формулы она обязана и без них. Чтобы это было не
 * обещанием, а проверкой, маршрут распознавания перехватывается и вызовы по нему
 * считаются: их должно быть ноль. Живое распознавание проверяется руками, на
 * своих ключах.
 *
 * **Сцена рисуется мышью, а не заливается запросом.** Чистовик строит сайт: он
 * делит росчерки на строки, он же помнит распознанное. Сцена, положенная на том
 * мимо страницы, не дала бы ни одной строки — и проверка проверяла бы службу,
 * которой в этом месте нечего делать.
 */
import { expect, test, type Page } from '@playwright/test'

import { signUpAndLogin, t, перейти } from './helpers'

/**
 * Один росчерк зигзагом от указанной точки холста.
 *
 * Зигзаг, а не прямая черта, по устройству группировки: строка на сцене
 * складывается из росчерков, чьи габариты перекрываются по вертикали, а у
 * горизонтальной черты высота почти нулевая — два таких росчерка рядом считались
 * бы разными строками, и проверка ловила бы собственную неаккуратность.
 */
async function росчерк(page: Page, x: number, y: number): Promise<void> {
  await page.mouse.move(x, y)
  await page.mouse.down()
  for (const [dx, dy] of [
    [25, -30],
    [50, 0],
    [75, -30],
    [100, 0],
  ]) {
    await page.mouse.move(x + (dx as number), y + (dy as number))
  }
  await page.mouse.up()
}

test('доска: письмо по холсту, строка руками, строки на том, проверка агентом', async ({
  page,
}) => {
  test.setTimeout(180_000)
  await signUpAndLogin(page, 'board')

  // Счётчик вызовов распознавателя ставится до того, как доска открыта: без
  // ключей наружу не должно уйти ни одного, и это утверждение, а не надежда.
  let распознаваний = 0
  await page.route('**/api/board/recognize', async (route) => {
    распознаваний += 1
    await route.abort()
  })

  // ── список досок пространства и первая доска ──────────────────────────────
  await page.getByRole('link', { name: t('shell.nav.board'), exact: true }).click()
  await expect(page.getByRole('heading', { name: t('board.home.title') })).toBeVisible()

  // Работы человек не выбирает: «Новая доска» заводит запись и каталог и сразу
  // открывает доску — спрашивать до неё нечего, условие называют уже на самой
  // доске. Работа, в которую доска легла, не показана нигде, но остаётся в
  // адресе: носитель прежний, решение работы.
  await page
    .getByRole('button', { name: t('board.home.create'), exact: true })
    .first()
    .click()
  await expect(page).toHaveURL(/\/board\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/)
  const [, projectId, boardId] = /\/board\/([0-9a-f-]{36})\/([0-9a-f-]{36})/.exec(
    page.url(),
  ) as RegExpExecArray

  // ── без ключей доска живёт, и об этом сказано словами ─────────────────────
  const полоса = page.getByTestId('board-ink')
  await expect(полоса).toBeVisible()
  await expect(полоса.getByText(t('board.ink.noKeys'))).toBeVisible()
  await expect(полоса.getByRole('link', { name: t('board.ink.toSettings') })).toHaveAttribute(
    'href',
    /\/settings\/agent$/,
  )

  // Общая панель агента на доске не показывается: у неё свой репетитор, своё
  // задание очереди и своя цена, а общая шлёт задание вида `agent`, которое на
  // доске откажется ещё до вызова модели.
  await expect(page.getByRole('button', { name: t('shell.agent.label') })).toHaveCount(0)

  // Проверять нечего — кнопка не нажимается и подписана почему.
  await expect(page.getByTestId('board-check')).toBeDisabled()
  await expect(page.getByText(t('board.ask.needLines'))).toBeVisible()

  // ── условие задачи текстом ────────────────────────────────────────────────
  await page.getByRole('button', { name: t('board.board.conditionEmpty') }).click()
  const поле = page.getByLabel(t('board.board.condition'))
  await поле.fill('Решить уравнение x^2 + 2x = 8')
  await поле.press('Enter')
  await expect(page.getByRole('button', { name: /Решить уравнение/ })).toBeVisible()

  // ── письмо по холсту ──────────────────────────────────────────────────────
  // Редактор грузится отдельным куском, а перо инструментом по умолчанию ставит
  // сам — но уже после того, как доразберёт начальные данные.
  const холст = page.locator('canvas').first()
  await expect(холст).toBeVisible({ timeout: 60_000 })
  const рамка = (await холст.boundingBox()) as { x: number; y: number }

  // Два росчерка рядом на одной высоте — это одна строка: строки на сцене
  // считаются по геометрии, а не по числу движений пера.
  await росчерк(page, рамка.x + 120, рамка.y + 180)
  await росчерк(page, рамка.x + 240, рамка.y + 180)

  // Строки — вложение к просьбе: они живут под скрепкой полосы действий, а не
  // отдельным чистовиком. Прочитанное при этом стои́т на самом холсте, призраком
  // под своей строкой, — но здесь ключей нет, и читать написанное некому.
  await page.getByTestId('board-attach').click()
  const строки = page.getByTestId('board-steps').locator('li')
  await expect.poll(() => строки.count(), { timeout: 30_000 }).toBe(1)
  // Ключей нет — читать написанное некому, и об этом сказано прямо, а не пустым
  // местом на месте формулы.
  await expect(строки.first()).toContainText(t('board.lines.unreadable', { n: 2 }))

  // ── строка, набранная руками ──────────────────────────────────────────────
  // Путь без пера и без ключей: человек говорит сам, что здесь написано, и
  // дальше распознаватель эту строку не трогает.
  await строки
    .first()
    .getByRole('button', { name: t('board.lines.type') })
    .click()
  await page.keyboard.type('x=2')

  // Строки уезжают на том готовыми: собрать их из сцены служба не может —
  // разбора рукописи у неё нет.
  const запись = page.waitForRequest(
    (запрос) => запрос.method() === 'PUT' && запрос.url().includes('/board/steps'),
  )
  await строки
    .first()
    .getByRole('button', { name: t('board.lines.save') })
    .click()
  const тело = JSON.parse((await запись).postData() ?? '{}') as {
    lines?: { id: string; latex: string; elements: string[]; confirmed: boolean }[]
  }
  expect(тело.lines).toHaveLength(1)
  // Подтверждения на доске нет: всё, что человек видит под своими росчерками,
  // уезжает репетитору, и поле совместимости у каждой строки истинно.
  expect(тело.lines?.[0]?.confirmed).toBe(true)
  const ушла = тело.lines?.[0] as { id: string; latex: string; elements: string[] }
  expect(ушла.latex).toContain('x')
  // Настоящие идентификаторы росчерков едут рядом с коротким именем строки: по
  // ним замечание репетитора становится выноской на холсте.
  expect(ушла.elements).toHaveLength(2)

  await expect(строки.first()).toHaveAttribute('data-state', 'manual')
  await expect(строки.first()).toContainText(t('board.lines.manual'))
  // Счётчик строк стои́т на скрепке: сколько их уедет вложением к просьбе.
  await expect(page.getByTestId('board-attach')).toContainText(t('board.lines.attached', { n: 1 }))

  // ── та же строка читается с тома ──────────────────────────────────────────
  const чтение = await page.request.get(
    `${new URL(page.url()).origin}/api/projects/${projectId}/board/steps?run=${boardId}`,
  )
  expect(чтение.ok()).toBeTruthy()
  const сТома = (await чтение.json()) as { steps: { id: string; latex: string }[] }
  expect(сТома.steps).toHaveLength(1)
  expect(сТома.steps[0]?.id).toBe(ушла.id)
  expect(сТома.steps[0]?.latex).toBe(ушла.latex)

  // ── прогон проверки через настоящую очередь ───────────────────────────────
  const проверить = page.getByTestId('board-check')
  await expect(проверить).toBeEnabled()
  await проверить.click()
  // Действие на экране всегда одно: пока идёт прогон, на месте трёх кнопок —
  // «Остановить».
  await expect(page.getByRole('button', { name: t('board.ask.stop') })).toBeVisible()

  const ответ = page.getByTestId('board-answer')
  await expect(ответ).toBeVisible({ timeout: 150_000 })
  // Вердикт — из объявленного набора, а не любой текст модели.
  await expect(ответ.locator('[data-verdict]')).toHaveAttribute(
    'data-verdict',
    /^(correct|wrong|unclear)$/,
  )

  // Главное обещание доски без ключей: наружу не ушло ни одного вызова.
  expect(распознаваний).toBe(0)

  // ── доска в списке пространства, и удаление уносит её целиком ─────────────
  await перейти(page, '/board')
  const карточки = page.getByTestId('board-list').locator('li')
  await expect.poll(() => карточки.count(), { timeout: 30_000 }).toBe(1)
  await карточки
    .first()
    .getByRole('button', { name: t('common.action.delete') })
    .click()
  await page.getByRole('button', { name: t('board.home.delete'), exact: true }).click()
  await expect(page.getByText(t('board.home.emptyTitle'))).toBeVisible({ timeout: 30_000 })
})

/**
 * Пустая доска: рисовать можно, просить — нет, панель складывается.
 *
 * Отдельной проверкой, потому что это другое состояние, а не другой шаг: цена
 * прогона обязана быть названа до нажатия, а не узнана из отказа, а холст на
 * планшете не должен становиться уже половины экрана.
 */
test('доска: пустую проверять нечего, а панель складывается в рейку', async ({ page }) => {
  test.setTimeout(90_000)
  await signUpAndLogin(page, 'board-empty')

  await перейти(page, '/board')
  await page
    .getByRole('button', { name: t('board.home.create'), exact: true })
    .first()
    .click()
  await expect(page).toHaveURL(/\/board\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/)

  // Холст живой, панель на месте, просить нечего.
  await expect(page.getByTestId('board-tutor')).toBeVisible()
  await expect(page.getByTestId('board-check')).toBeDisabled()
  await page.getByTestId('board-attach').click()
  await expect(page.getByText(t('board.lines.emptyTitle'))).toBeVisible()

  await page.getByRole('button', { name: t('board.board.panelHide') }).click()
  await expect(page.getByTestId('board-tutor')).toHaveCount(0)
  await page.getByRole('button', { name: t('board.board.panelShow') }).click()
  await expect(page.getByTestId('board-tutor')).toBeVisible()
})
