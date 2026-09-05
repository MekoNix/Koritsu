/**
 * Коробка пожеланий: что она сохраняет и когда даёт это сделать.
 *
 * Проверяется не вёрстка, а два правила, каждое из которых стоит человеку
 * потерянного текста:
 *
 * 1. **набранное не затирается ответом службы.** Запрос за пожеланиями едет
 *    параллельно с тем, как человек их правит, и «положить приехавшее в поля»
 *    без оглядки на правку стёрло бы текст под руками;
 * 2. **сохраняется то, что видно на экране,** и только когда есть что
 *    сохранять: кнопка на неизменённых пожеланиях писала бы в проект то же
 *    самое.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { WishesBox } from './WishesBox'
import { ПУСТЫЕ_ПОЖЕЛАНИЯ } from './stages'

function нарисовать(над: Partial<Parameters<typeof WishesBox>[0]> = {}) {
  const onSave = vi.fn()
  render(
    <WishesBox
      wishes={ПУСТЫЕ_ПОЖЕЛАНИЯ}
      loading={false}
      saving={false}
      error={null}
      started={false}
      disabled={false}
      onSave={onSave}
      {...над}
    />,
  )
  return onSave
}

describe('WishesBox', () => {
  it('сохраняет набранный текст и обе пометки', async () => {
    const onSave = нарисовать()
    const человек = userEvent.setup()

    expect(screen.getByRole('button', { name: /Сохранить пожелания/ })).toBeDisabled()

    await человек.type(screen.getByLabelText(/Пожелания к работе/), 'покороче')
    await человек.click(screen.getByLabelText(/Показать строение работы/))
    await человек.click(screen.getByRole('button', { name: /Сохранить пожелания/ }))

    expect(onSave).toHaveBeenCalledWith({
      text: 'покороче',
      show_task: false,
      show_structure: true,
    })
  })

  it('у заведённой работы говорит, что правка доедет только в новой', () => {
    // Сценарий читает пожелания, когда заводит работу, и заведённой их уже не
    // меняет. Промолчать об этом значило бы дать человеку править то, что
    // сегодня ни на что не влияет.
    нарисовать({ started: true })
    expect(screen.getByText(/доедет до модели только в новой работе/)).toBeInTheDocument()
  })
})
