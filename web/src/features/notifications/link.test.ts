/**
 * Тесты разбора ссылки уведомления.
 *
 * Ломается это молча и обиднее всего: уведомление приходит, человек по нему
 * кликает и попадает не туда (или в «страница не найдена»), причём заметно это
 * только руками. Отсюда три случая:
 *
 * 1. вид задания решает, на какой экран вести (разбор — в работу, тег — в
 *    отчёт, kadai — на свою страницу);
 * 2. **проекта нет — ссылки нет**: ссылка в никуда запрещена прямо;
 * 3. собранный файл скачивается по адресу артефакта той же работы.
 */
import { describe, expect, it } from 'vitest'

import { notificationDownload, notificationLink } from './link'

const PID = 'a1b2c3d4-0000-4000-8000-000000000001'

describe('куда ведёт уведомление', () => {
  it('разбор файла — в опись работы', () => {
    expect(notificationLink({ job_kind: 'parse', project_id: PID })).toBe(`/projects/${PID}`)
  })

  it('заполнение тега и сборка — на экран отчёта', () => {
    expect(notificationLink({ job_kind: 'fill_tag', project_id: PID })).toBe(`/reports/${PID}`)
    expect(notificationLink({ job_kind: 'build', project_id: PID })).toBe(`/reports/${PID}`)
  })

  it('kadai — на свою страницу', () => {
    expect(notificationLink({ job_kind: 'kadai_run', project_id: PID })).toBe(`/kadai/${PID}`)
  })

  it('незнакомый вид ведёт на карточку работы', () => {
    expect(notificationLink({ job_kind: 'что-то новое', project_id: PID })).toBe(`/projects/${PID}`)
  })

  it('без работы ссылки нет вовсе', () => {
    expect(notificationLink({ job_kind: 'probe', project_id: null })).toBeNull()
    expect(notificationLink(undefined)).toBeNull()
  })
})

describe('что скачать по уведомлению', () => {
  it('берёт артефакт из data.artifacts', () => {
    const файл = notificationDownload({
      job_kind: 'export',
      project_id: PID,
      artifacts: { file: 'art-1' },
    })
    expect(файл).toEqual({ url: `/api/projects/${PID}/artifacts/art-1`, kind: 'file' })
  })

  it('из пары DOCX и PDF предлагает PDF: его открывают, а не правят', () => {
    const файл = notificationDownload({
      job_kind: 'build',
      project_id: PID,
      artifacts: { docx: 'art-d', pdf: 'art-p' },
    })
    expect(файл?.kind).toBe('pdf')
  })

  it('файлов нет — скачивать нечего', () => {
    expect(notificationDownload({ job_kind: 'fill_tag', project_id: PID })).toBeNull()
    expect(notificationDownload({ job_kind: 'build', artifacts: { pdf: 'x' } })).toBeNull()
  })
})
