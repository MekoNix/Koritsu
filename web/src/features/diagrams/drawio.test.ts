/**
 * Проверки разговора с встроенным draw.io.
 *
 * Проверяется здесь не «работает ли редактор» (он чужой и живёт в сети), а то
 * единственное, что наше и что ломается молча: форма сообщения и разбор
 * ответа. Сломанный `load` не даёт ни ошибки, ни исключения — кадр просто
 * остаётся пустым, и это самая дорогая из поломок: она выглядит как «нет
 * сети».
 */
import { describe, expect, it } from 'vitest'

import {
  APP_ORIGIN,
  EMBED_ORIGIN,
  EMPTY_XML,
  VIEWER_ORIGIN,
  drawioWindowUrl,
  embedUrl,
  loadMessage,
  parseEmbedEvent,
  windowOrigin,
} from './drawio'

describe('embedUrl', () => {
  it('говорит кадру, что он встроен и общается JSON-ом', () => {
    const url = new URL(embedUrl({ dark: true }))
    expect(url.origin).toBe(EMBED_ORIGIN)
    expect(url.searchParams.get('embed')).toBe('1')
    expect(url.searchParams.get('proto')).toBe('json')
    expect(url.searchParams.get('dark')).toBe('1')
    expect(url.searchParams.get('noSaveBtn')).toBe('1')
  })

  it('светлый режим сайта — светлый редактор', () => {
    expect(new URL(embedUrl({ dark: false })).searchParams.get('dark')).toBe('0')
  })
})

describe('loadMessage', () => {
  it('собирает сообщение «покажи этот XML» с включённым autosave', () => {
    const тело = JSON.parse(loadMessage('<mxfile>тест</mxfile>')) as Record<string, unknown>
    expect(тело).toEqual({ action: 'load', autosave: 1, xml: '<mxfile>тест</mxfile>' })
  })

  it('пустая схема заменяется холстом: кадру нужно показать хоть что-то', () => {
    const тело = JSON.parse(loadMessage('')) as { xml: string }
    expect(тело.xml).toBe(EMPTY_XML)
  })
})

describe('parseEmbedEvent', () => {
  it('читает событие строкой JSON', () => {
    expect(parseEmbedEvent('{"event":"init"}')).toEqual({
      event: 'init',
      xml: undefined,
      data: undefined,
    })
  })

  it('читает событие объектом и забирает XML правки', () => {
    expect(parseEmbedEvent({ event: 'autosave', xml: '<mxfile/>' })).toMatchObject({
      event: 'autosave',
      xml: '<mxfile/>',
    })
  })

  it('чужое сообщение — не событие', () => {
    expect(parseEmbedEvent('не json')).toBeNull()
    expect(parseEmbedEvent('{"foo":1}')).toBeNull()
    expect(parseEmbedEvent(null)).toBeNull()
    expect(parseEmbedEvent({ event: 42 })).toBeNull()
  })
})

describe('drawioWindowUrl', () => {
  it('правки — на app.diagrams.net, просмотр — на viewer.diagrams.net', () => {
    expect(new URL(drawioWindowUrl('edit', { dark: true })).origin).toBe(APP_ORIGIN)
    expect(new URL(drawioWindowUrl('view', { dark: true })).origin).toBe(VIEWER_ORIGIN)
    expect(windowOrigin('edit')).toBe(APP_ORIGIN)
    expect(windowOrigin('view')).toBe(VIEWER_ORIGIN)
  })

  it('окно говорит тем же протоколом, что и кадр: схема приедет сообщением', () => {
    const url = new URL(drawioWindowUrl('edit', { dark: false, title: 'Лабораторная 4' }))
    expect(url.searchParams.get('embed')).toBe('1')
    expect(url.searchParams.get('proto')).toBe('json')
    expect(url.searchParams.get('title')).toBe('Лабораторная 4')
    expect(url.searchParams.get('dark')).toBe('0')
  })

  it('просмотр открывается лупой, а не редактором', () => {
    const url = new URL(drawioWindowUrl('view', { dark: false }))
    expect(url.searchParams.get('lightbox')).toBe('1')
    expect(url.searchParams.get('libraries')).toBeNull()
  })

  it('длина схемы на адрес не влияет — её в адресе нет вовсе', () => {
    // Прежде XML уезжал в `#R…`, и длинная схема гасила кнопку. Теперь адрес
    // не несёт ни куска схемы: ни решётки, ни данных.
    const адрес = drawioWindowUrl('edit', { dark: false })
    expect(адрес).not.toContain('#')
    expect(адрес.length).toBeLessThan(200)
  })
})
