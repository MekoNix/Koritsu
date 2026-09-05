/**
 * AppearanceSection — тема, светлый/тёмный, шрифт и плотность.
 *
 * Своего хранилища здесь нет и быть не должно: всё это уже хранит каркас
 * (`theme/store.ts`, один ключ `koritsu.appearance` в `localStorage`, который
 * читает встроенный скрипт `index.html` до первого рендера). Раздел только
 * зовёт `set()` из `useAppearance()` — поэтому выбор переживает перезагрузку
 * без единой строки здесь и страница не мигает чужими цветами.
 *
 * **«Как в системе» — кнопка, а не третий вариант.** Хранимых вариантов два,
 * `light` и `dark` (`data-mode` на `<html>` — значение CSS, а не намерение), и
 * заводить третий пришлось бы в общем файле каркаса. Кнопка подставляет то,
 * что сейчас выбрано в операционной системе; постоянного слежения за системой
 * здесь нет.
 */
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import {
  DENSITIES,
  FONTS,
  NATIVE_MODE,
  THEMES,
  THEME_NAME,
  useAppearance,
  type Density,
  type Mode,
  type Theme,
} from '@/theme'
import { Button, Card, Icon, Segmented, Select } from '@/ui'

/**
 * Четыре цвета темы для образца: фон, поверхность, акцент, текст. Значения
 * взяты из `themes/<id>-<родной режим>.css` макета — брать их из переменных на
 * `<html>` нельзя, там всегда только включённая тема.
 */
const SWATCHES: Record<Theme, readonly string[]> = {
  slate: ['#08090B', '#0F1114', '#6E7CFF', '#DFE2E8'],
  paper: ['#EDE8DE', '#FBF8F2', '#2B4372', '#23252B'],
  linear: ['#08090A', '#1B1C20', '#7C8AF5', '#F7F8F8'],
  glass: ['#141922', '#2A3240', '#8FB8FF', '#8FE0C6'],
}

/** Что сейчас выбрано в операционной системе. */
function systemMode(): Mode {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function AppearanceSection() {
  const t = useT()
  const { appearance, set } = useAppearance()

  return (
    <>
      <Card title={t('settings.appearance.theme')}>
        <div
          role="radiogroup"
          aria-label={t('settings.appearance.theme')}
          className="grid gap-s3 sm:grid-cols-3"
        >
          {THEMES.map((theme) => {
            const selected = theme === appearance.theme
            return (
              <button
                key={theme}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => set({ theme })}
                className={cn(
                  'flex flex-col gap-1.5 rounded-md border bg-surface p-s3 text-left transition-colors',
                  selected
                    ? 'border-accent ring-[3px] ring-accent-bg'
                    : 'border-line hover:border-line-strong',
                )}
              >
                <span className="flex h-7 gap-1 overflow-hidden rounded-sm">
                  {SWATCHES[theme].map((color) => (
                    <i key={color} className="flex-1" style={{ background: color }} />
                  ))}
                </span>
                <span className="text-sm font-semibold text-ink-strong">{THEME_NAME[theme]}</span>
                <span className="text-xs text-muted">
                  {NATIVE_MODE[theme] === 'dark'
                    ? t('settings.appearance.themeNativeDark')
                    : t('settings.appearance.themeNativeLight')}
                </span>
              </button>
            )
          })}
        </div>

        <div className="flex flex-wrap items-end gap-s4">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-ink">{t('settings.appearance.mode')}</span>
            <div className="flex flex-wrap items-center gap-s2">
              <Segmented<Mode>
                label={t('settings.appearance.mode')}
                value={appearance.mode}
                onChange={(mode) => set({ mode })}
                options={[
                  { value: 'light', label: t('settings.appearance.modeLight') },
                  { value: 'dark', label: t('settings.appearance.modeDark') },
                ]}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => set({ mode: systemMode() })}
                title={t('settings.appearance.modeSystemHint')}
              >
                <Icon name="refresh" size={14} />
                {t('settings.appearance.modeSystem')}
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-ink">{t('settings.appearance.density')}</span>
            <Segmented<Density>
              label={t('settings.appearance.density')}
              value={appearance.density}
              onChange={(density) => set({ density })}
              options={DENSITIES.map((density) => ({
                value: density,
                label:
                  density === 'compact'
                    ? t('settings.appearance.densityCompact')
                    : t('settings.appearance.densityComfortable'),
              }))}
            />
          </div>
        </div>
      </Card>

      <Card title={t('settings.appearance.font')} desc={t('settings.appearance.fontHint')}>
        <Select
          label={t('settings.appearance.font')}
          value={appearance.font}
          onChange={(e) => set({ font: e.target.value })}
        >
          {FONTS.map((font) => (
            <option key={font.id} value={font.stack}>
              {font.nameKey ? t(font.nameKey) : font.name} —{' '}
              {font.bundled
                ? t('settings.appearance.fontBundled')
                : t('settings.appearance.fontSystem')}
            </option>
          ))}
        </Select>
        {/* Образец — сразу тем шрифтом, который выбран: список названий ничего
            не говорит о том, как выглядит кириллица. */}
        <p className="rounded-sm border border-line bg-surface-2 px-s3 py-s2 text-md text-ink-strong">
          {t('settings.appearance.sample')}
        </p>
      </Card>
    </>
  )
}
