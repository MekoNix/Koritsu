/**
 * dialogs — диалоги строки меню: Найти, Перейти к строке, Перейти к адресу,
 * Добавить наблюдение, Параметры сборки, Горячие клавиши, Переименовать,
 * Сохранить как.
 *
 * Все на `Dialog` из `@/ui`: фокус, Esc и возврат фокуса к месту, откуда окно
 * открыли, делает Radix. Проверка — до закрытия: окно с ошибкой остаётся
 * открытым и говорит, что не так, а не закрывается молча.
 */
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, Dialog, Input, Select } from '@/ui'

import {
  fetchAsmProgram,
  putAsmSettings,
  putAsmSource,
  useAsmStatus,
  useCreateAsmProgram,
  useUpdateAsmProgram,
} from '../api'
import { useAsm, useAsmUi, type AsmDialogId } from '../store'
import { regHex, type AsmSettings, type AsmStep } from '../types'
import { fileBase, useAsmActions } from './actions'

const FORM = 'asm-dialog-form'

export function AsmDialogs() {
  const ui = useAsmUi()
  const d = ui.dialog
  if (!d) return null
  const Body = BODIES[d]
  // Ключ — id диалога: новое открытие начинает с чистого состояния полей.
  return <Body key={d} />
}

const BODIES: Record<AsmDialogId, () => ReactNode> = {
  find: FindDialog,
  line: LineDialog,
  addr: AddrDialog,
  watch: WatchDialog,
  buildOpts: BuildOptsDialog,
  hotkeys: HotkeysDialog,
  rename: RenameDialog,
  saveAs: SaveAsDialog,
}

function Shell({
  title,
  ok,
  busy,
  onSubmit,
  children,
  cancel = true,
}: {
  title: string
  ok: string
  busy?: boolean
  onSubmit: () => void
  children: ReactNode
  cancel?: boolean
}) {
  const t = useT()
  const ui = useAsmUi()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && ui.closeDialog()}
      title={title}
      footer={
        <>
          {cancel && (
            <Button variant="ghost" onClick={ui.closeDialog}>
              {t('common.action.cancel')}
            </Button>
          )}
          <Button variant="primary" type="submit" form={FORM} loading={busy}>
            {ok}
          </Button>
        </>
      }
    >
      <form id={FORM} className="flex flex-col gap-s3" onSubmit={submit} noValidate>
        {children}
      </form>
    </Dialog>
  )
}

function FindDialog() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const actions = useAsmActions()
  const [q, setQ] = useState(ui.findQuery)
  const [err, setErr] = useState<string>()

  const submit = () => {
    const query = q.trim().toLowerCase()
    if (!query) return setErr(t('asm.dialog.find.empty'))
    ui.setFindQuery(q.trim())
    const lines = (asm.program?.source ?? '').split('\n')
    const hits = lines.flatMap((l, i) => (l.toLowerCase().includes(query) ? [i + 1] : []))
    if (!hits.length) return setErr(t('asm.dialog.find.none', { q: q.trim() }))
    const n = hits.find((x) => x > (asm.cursorLine ?? 0)) ?? hits[0]!
    ui.closeDialog()
    actions.gotoLine(n)
    asm.toast(t('asm.dialog.find.hits', { line: n, n: hits.length }))
  }

  return (
    <Shell title={t('asm.dialog.find.title')} ok={t('asm.dialog.find.ok')} onSubmit={submit}>
      <Input
        autoFocus
        label={t('asm.dialog.find.label')}
        value={q}
        error={err}
        spellCheck={false}
        autoComplete="off"
        className="font-mono"
        onChange={(e) => {
          setQ(e.target.value)
          setErr(undefined)
        }}
      />
    </Shell>
  )
}

function LineDialog() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const actions = useAsmActions()
  const total = (asm.program?.source ?? '').split('\n').length
  const [v, setV] = useState(String(asm.cursorLine ?? 1))
  const [err, setErr] = useState<string>()

  const submit = () => {
    const n = Number(v)
    if (!Number.isInteger(n) || n < 1 || n > total) return setErr(t('asm.dialog.line.bad', { n: total }))
    ui.closeDialog()
    actions.gotoLine(n)
  }

  return (
    <Shell title={t('asm.dialog.line.title')} ok={t('asm.dialog.line.ok')} onSubmit={submit}>
      <Input
        autoFocus
        type="number"
        min={1}
        max={total}
        label={t('asm.dialog.line.label', { n: total })}
        value={v}
        error={err}
        className="font-mono"
        onChange={(e) => {
          setV(e.target.value)
          setErr(undefined)
        }}
      />
    </Shell>
  )
}

const СЕГМЕНТЫ = ['cs', 'ds', 'ss', 'es'] as const
const СМЕЩЕНИЯ = ['si', 'di', 'bp', 'sp', 'ip', 'bx'] as const

/**
 * `СЕГМЕНТ:СМЕЩЕНИЕ`, где любая половина — регистр или до четырёх hex-цифр.
 * Регистры подставляются значением текущего шага; без трассы их не во что
 * подставить, и адрес с регистром не разбирается.
 */
function parseAddress(text: string, step: AsmStep | undefined): { seg: string; off: string } | null {
  const m = /^\s*([0-9a-z]{1,4})\s*:\s*([0-9a-z]{1,4})\s*$/i.exec(text)
  if (!m) return null
  const part = (s: string, regs: readonly string[]) => {
    const low = s.toLowerCase()
    if (regs.includes(low)) {
      const v = regHex(step, low)
      return v ? v.toUpperCase().padStart(4, '0') : null
    }
    return /^[0-9a-f]{1,4}$/i.test(s) ? s.toUpperCase().padStart(4, '0') : null
  }
  const seg = part(m[1]!, СЕГМЕНТЫ)
  const off = part(m[2]!, СМЕЩЕНИЯ)
  return seg && off ? { seg, off } : null
}

function AddrDialog() {
  const asm = useAsm()
  return asm.toolchain.memory === 'flat' ? <FlatAddrDialog /> : <SegmentedAddrDialog />
}

/**
 * Адрес плоской памяти: число (`0x140003000`, `140003000h`), имя переменной,
 * регистр — разбирает описатель режима по текущему шагу и символам сборки.
 */
function FlatAddrDialog() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const tc = asm.toolchain
  const start = asm.selection?.kind === 'cell' && asm.selection.seg == null ? `0x${asm.selection.off}` : ''
  const [v, setV] = useState(start)
  const [err, setErr] = useState<string>()

  const submit = () => {
    const a = tc.addr.parse(v, asm.step, asm.run)
    if (!a) return setErr(t('asm.dialog.addr.badFlat'))
    ui.closeDialog()
    asm.select({ kind: 'cell', seg: null, off: a.off.toString(16).toUpperCase().padStart(tc.addr.width, '0') })
    asm.openWindow('dump', { focus: true })
  }

  return (
    <Shell title={t('asm.dialog.addr.title')} ok={t('asm.dialog.addr.ok')} onSubmit={submit}>
      <Input
        autoFocus
        label={t('asm.dialog.addr.labelFlat')}
        value={v}
        error={err}
        spellCheck={false}
        autoComplete="off"
        className="font-mono"
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => {
          setV(e.target.value)
          setErr(undefined)
        }}
      />
    </Shell>
  )
}

function SegmentedAddrDialog() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const start =
    asm.selection?.kind === 'cell' ? `${asm.selection.seg}:${asm.selection.off}` : 'DS:0000'
  const [v, setV] = useState(start)
  const [err, setErr] = useState<string>()

  const submit = () => {
    const a = parseAddress(v, asm.step)
    if (!a) return setErr(t(asm.step ? 'asm.dialog.addr.bad' : 'asm.dialog.addr.badNoTrace'))
    ui.closeDialog()
    asm.select({ kind: 'cell', seg: a.seg, off: a.off })
    asm.openWindow('dump', { focus: true })
  }

  return (
    <Shell title={t('asm.dialog.addr.title')} ok={t('asm.dialog.addr.ok')} onSubmit={submit}>
      <Input
        autoFocus
        label={t('asm.dialog.addr.label')}
        value={v}
        error={err}
        spellCheck={false}
        autoComplete="off"
        className="font-mono"
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => {
          setV(e.target.value)
          setErr(undefined)
        }}
      />
    </Shell>
  )
}

const РЕГИСТРЫ = new Set([
  'ax', 'bx', 'cx', 'dx', 'si', 'di', 'bp', 'sp', 'ip', 'cs', 'ds', 'ss', 'es', 'flags',
  'al', 'ah', 'bl', 'bh', 'cl', 'ch', 'dl', 'dh',
  'eax', 'ebx', 'ecx', 'edx', 'esi', 'edi', 'ebp', 'esp', 'eip',
])
const ФЛАГИ = new Set(['of', 'df', 'if', 'sf', 'zf', 'af', 'pf', 'cf'])

/** Регистры x86-64 со всеми половинками: rax/eax/ax/al/ah, rsi/esi/si/sil, r8/r8d/r8w/r8b, rip, rflags. */
const РЕГИСТР_64 = /^(?:[re]?[abcd]x|[abcd][lh]|[re]?(?:si|di|bp|sp)|(?:si|di|bp|sp)l|r(?:[89]|1[0-5])[dwb]?|[re]?ip|r?e?flags|[cdsefg]s)$/

/**
 * Годится ли выражение наблюдения в плоской памяти: регистр, флаг (с TF), адрес
 * или имя переменной. С трассой адрес проверяет описатель режима; без неё имён
 * ещё нет — верим на слово, проверит окно.
 */
function watchValidFlat(expr: string, asm: ReturnType<typeof useAsm>): boolean {
  const e = expr.trim().toLowerCase()
  if (РЕГИСТР_64.test(e) || ФЛАГИ.has(e) || e === 'tf') return true
  if (asm.toolchain.addr.parse(expr, asm.step, asm.run)) return true
  const sized = /^(?:(?:byte|word|dword|qword)(?:\s+ptr)?\s*)?\[[^\]]+\]$/.test(e)
  if (sized) return true
  return !asm.run?.build?.symbols.length && /^[a-z_.$@?][\w.$@?]*(?:\s*(?:\[\s*\d+\s*\]|\+\s*(?:0x)?[0-9a-f]+))?$/.test(e)
}

/** Годится ли выражение наблюдения: регистр, флаг, адрес или переменная `[индекс]`. */
function watchValid(expr: string, symbols: string[] | null): boolean {
  const e = expr.trim().toLowerCase()
  if (РЕГИСТРЫ.has(e) || ФЛАГИ.has(e)) return true
  if (/^[0-9a-z]{1,4}\s*:\s*[0-9a-z]{1,4}$/.test(e)) return true
  const m = /^([a-z_@$?][\w@$?]*)(?:\s*\[\s*\d+\s*\])?$/.exec(e)
  if (!m) return false
  // Без сборки имён переменных ещё нет: верим на слово, проверит окно.
  return !symbols || symbols.includes(m[1]!)
}

function WatchDialog() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const [v, setV] = useState('')
  const [err, setErr] = useState<string>()

  const submit = () => {
    const expr = v.trim()
    if (!expr) return setErr(t('asm.dialog.watch.empty'))
    const flat = asm.toolchain.memory === 'flat'
    const symbols = asm.run?.build?.symbols.map((s) => s.name.toLowerCase()) ?? null
    const ok = flat ? watchValidFlat(expr, asm) : watchValid(expr, symbols?.length ? symbols : null)
    if (!ok) return setErr(t(flat ? 'asm.dialog.watch.badFlat' : 'asm.dialog.watch.bad'))
    const was = asm.settings.watches
    if (!was.some((w) => w.toLowerCase() === expr.toLowerCase())) asm.updateSettings({ watches: [...was, expr] })
    ui.closeDialog()
    asm.openWindow('watch', { focus: true })
  }

  return (
    <Shell title={t('asm.dialog.watch.title')} ok={t('asm.dialog.watch.ok')} onSubmit={submit}>
      <Input
        autoFocus
        label={t(asm.toolchain.memory === 'flat' ? 'asm.dialog.watch.labelFlat' : 'asm.dialog.watch.label')}
        value={v}
        error={err}
        spellCheck={false}
        autoComplete="off"
        className="font-mono"
        onChange={(e) => {
          setV(e.target.value)
          setErr(undefined)
        }}
      />
    </Shell>
  )
}

/** «Параметры сборки» — по режиму программы: галки TASM или строки ключей `as`/`ld`. */
function BuildOptsDialog() {
  const asm = useAsm()
  return asm.toolchain.id === 'tasm' ? <TasmBuildOpts /> : <GnuBuildOpts />
}

/**
 * Версия инструментов в пределах режима. Поле видно, только если версий больше
 * одной: одна версия — выбирать нечего. Меняется запросом `PATCH` при сохранении
 * диалога и действует со следующей сборки.
 */
function useVersionField() {
  const t = useT()
  const asm = useAsm()
  const status = useAsmStatus()
  const update = useUpdateAsmProgram()
  const versions = status.data?.toolchains.find((x) => x.id === asm.toolchain.id)?.versions ?? []
  const current = asm.program?.asmVersion ?? ''
  const [v, setV] = useState(current)
  const field =
    versions.length > 1 ? (
      <Select label={t('asm.dialog.build.version')} value={v} onChange={(e) => setV(e.target.value)}>
        {versions.map((x) => (
          <option key={x.id} value={x.id}>
            {x.available ? x.title : `${x.title} · ${t('asm.new.versionMissing')}`}
          </option>
        ))}
      </Select>
    ) : null
  const apply = async () => {
    if (versions.length > 1 && v && v !== current)
      await update.mutateAsync({ projectId: asm.projectId, programId: asm.programId, toolchainVersion: v })
  }
  return { field, apply, busy: update.isPending }
}

/** Ключи из настроек как список строк: у `keys` описателя тип — любое поле настроек. */
function flagsOf(s: AsmSettings, key: keyof AsmSettings): string[] {
  const v = s[key]
  return Array.isArray(v) ? v.map(String) : []
}

const splitFlags = (text: string) => (text.trim() ? text.trim().split(/\s+/) : [])

/**
 * Ключи GNU `as` и `ld` строкой через пробел. Проверяет их служба по перечню
 * разрешённого; листинг, имена файлов, `-L` и `-lkernel32` добавляет ядро, в
 * настройки они не пишутся. Превью — команды так, как их набирают руками.
 */
function GnuBuildOpts() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const tc = asm.toolchain
  const [k0, k1] = tc.buildFlags.keys
  const [a, setA] = useState(flagsOf(asm.settings, k0).join(' '))
  const [b, setB] = useState(flagsOf(asm.settings, k1).join(' '))
  const [err, setErr] = useState<string>()
  const version = useVersionField()
  const base = fileBase(asm.program?.name ?? '')
  const next = { ...asm.settings, [k0]: splitFlags(a), [k1]: splitFlags(b) } as AsmSettings

  const submit = async () => {
    try {
      await version.apply()
    } catch (e) {
      return setErr(errorText(e))
    }
    asm.updateSettings({ [k0]: next[k0], [k1]: next[k1] } as Partial<AsmSettings>)
    ui.closeDialog()
    asm.toast(t('asm.dialog.build.applied'))
  }

  return (
    <Shell title={t('asm.dialog.build.title')} ok={t('asm.dialog.build.ok')} busy={version.busy} onSubmit={() => void submit()}>
      {version.field}
      <Input
        autoFocus
        label={t('asm.dialog.build.flagsOf', { tool: tc.tools[0] })}
        value={a}
        spellCheck={false}
        autoComplete="off"
        className="font-mono"
        onChange={(e) => setA(e.target.value)}
      />
      <Input
        label={t('asm.dialog.build.flagsOf', { tool: tc.tools[1] })}
        value={b}
        spellCheck={false}
        autoComplete="off"
        className="font-mono"
        onChange={(e) => setB(e.target.value)}
      />
      <p className="text-xs text-muted">{t('asm.dialog.build.flagsHint')}</p>
      <p className="text-xs text-muted">{t('asm.dialog.build.commands')}</p>
      <pre className="whitespace-pre-wrap rounded-sm border border-line bg-surface-3 px-s3 py-s2 font-mono text-xs">
        {tc.buildFlags.preview(next, base)}
      </pre>
      {err && <p className="text-sm text-err">{err}</p>}
    </Shell>
  )
}

function TasmBuildOpts() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const { tasm_flags, tlink_flags } = asm.settings
  const has = (list: string[], f: string) => list.some((x) => x.toLowerCase() === f)
  const [zi, setZi] = useState(has(tasm_flags, '/zi'))
  const [l, setL] = useState(has(tasm_flags, '/l'))
  const [v, setV] = useState(has(tlink_flags, '/v'))
  const [err, setErr] = useState<string>()
  const version = useVersionField()
  const base = fileBase(asm.program?.name ?? '')

  // Прочие ключи, заданные раньше, не теряются: диалог правит только свои три.
  const other = (list: string[], mine: string[]) => list.filter((x) => !mine.includes(x.toLowerCase()))
  const tasm = [...(zi ? ['/zi'] : []), ...(l ? ['/l'] : []), ...other(tasm_flags, ['/zi', '/l'])]
  const tlink = [...(v ? ['/v'] : []), ...other(tlink_flags, ['/v'])]

  const submit = async () => {
    try {
      await version.apply()
    } catch (e) {
      return setErr(errorText(e))
    }
    asm.updateSettings({ tasm_flags: tasm, tlink_flags: tlink })
    ui.closeDialog()
    asm.toast(t('asm.dialog.build.applied'))
  }

  const box = (checked: boolean, set: (b: boolean) => void, flag: string, text: string) => (
    <label className="flex items-start gap-s2 text-sm text-ink">
      <input type="checkbox" className="mt-1" checked={checked} onChange={(e) => set(e.target.checked)} />
      <span>
        <b className="font-mono">{flag}</b> — {text}
      </span>
    </label>
  )

  return (
    <Shell title={t('asm.dialog.build.title')} ok={t('asm.dialog.build.ok')} busy={version.busy} onSubmit={() => void submit()}>
      {version.field}
      {box(zi, setZi, '/zi', t('asm.dialog.build.zi'))}
      {box(l, setL, '/l', t('asm.dialog.build.l'))}
      {box(v, setV, '/v', t('asm.dialog.build.v'))}
      <pre className="whitespace-pre-wrap rounded-sm border border-line bg-surface-3 px-s3 py-s2 font-mono text-xs">
        {asm.toolchain.buildFlags.preview({ ...asm.settings, tasm_flags: tasm, tlink_flags: tlink }, base)}
      </pre>
      {!l && <p className="text-sm text-warn">{t('asm.dialog.build.noListing')}</p>}
      {err && <p className="text-sm text-err">{err}</p>}
    </Shell>
  )
}

function HotkeysDialog() {
  const t = useT()
  const ui = useAsmUi()
  const rows: [string, string][] = [
    ['F1', 'help'],
    ['F2', 'breakpoint'],
    ['F4', 'toCursor'],
    ['F7 / F8', 'step'],
    ['Shift+F8', 'stepBack'],
    ['F9', 'toBreakpoint'],
    ['Home / End', 'startEnd'],
    ['F6', 'nextGroup'],
    ['F10 / Alt', 'menubar'],
    ['Ctrl+Enter', 'buildRun'],
    ['Ctrl+B', 'buildOnly'],
    ['Ctrl+J', 'askAgent'],
    ['Ctrl+F / Ctrl+G', 'findLine'],
    ['Ctrl+S', 'save'],
    ['Alt+1…9', 'window'],
    ['Ctrl+Tab', 'nextTab'],
    ['Ctrl+Alt+←↑→↓', 'moveTab'],
  ]
  return (
    <Shell title={t('asm.dialog.hotkeys.title')} ok={t('asm.dialog.hotkeys.ok')} cancel={false} onSubmit={ui.closeDialog}>
      <table className="w-full border-collapse text-sm">
        <tbody>
          {rows.map(([keysText, id]) => (
            <tr key={id} className="border-b border-line">
              <td className="whitespace-nowrap py-1 pr-s4 font-mono text-xs font-semibold text-ink-strong">{keysText}</td>
              <td className="py-1 text-ink">{t(`asm.hotkeys.${id}`)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  )
}

function RenameDialog() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const rename = useUpdateAsmProgram()
  const [v, setV] = useState(asm.program?.name ?? '')
  const [err, setErr] = useState<string>()

  const submit = () => {
    const name = v.trim()
    if (!name) return setErr(t('asm.dialog.rename.empty'))
    rename.mutate(
      { projectId: asm.projectId, programId: asm.programId, name },
      { onSuccess: ui.closeDialog, onError: (e) => setErr(errorText(e)) },
    )
  }

  return (
    <Shell title={t('asm.dialog.rename.title')} ok={t('asm.dialog.rename.ok')} busy={rename.isPending} onSubmit={submit}>
      <Input
        autoFocus
        label={t('asm.dialog.rename.label')}
        value={v}
        error={err}
        onChange={(e) => {
          setV(e.target.value)
          setErr(undefined)
        }}
      />
    </Shell>
  )
}

/**
 * «Сохранить как» — новая программа того же пространства, того же режима и версии
 * инструментов, с текущим исходником и настройками. Прогоны и переписка не
 * копируются: они про прежнюю программу.
 */
function SaveAsDialog() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const navigate = useNavigate()
  const workspace = useCurrentWorkspace()
  const create = useCreateAsmProgram()
  const [v, setV] = useState(`${asm.program?.name ?? ''} (2)`.trim())
  const [err, setErr] = useState<string>()
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    const name = v.trim()
    const ws = workspace.data?.id
    if (!name) return setErr(t('asm.dialog.rename.empty'))
    if (!ws) return
    setBusy(true)
    try {
      const p = await create.mutateAsync({
        workspaceId: ws,
        name,
        toolchain: asm.toolchain.id,
        ...(asm.program?.asmVersion ? { toolchainVersion: asm.program.asmVersion } : {}),
      })
      const fresh = await fetchAsmProgram(p.project_id, p.program_id)
      await putAsmSource(p.project_id, p.program_id, asm.program?.source ?? '', fresh.version)
      await putAsmSettings(p.project_id, p.program_id, asm.settings)
      ui.closeDialog()
      navigate(`/asm/${p.project_id}/${p.program_id}`)
    } catch (e) {
      setErr(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell title={t('asm.dialog.saveAs.title')} ok={t('asm.dialog.saveAs.ok')} busy={busy} onSubmit={() => void submit()}>
      <Input
        autoFocus
        label={t('asm.dialog.rename.label')}
        value={v}
        error={err}
        onChange={(e) => {
          setV(e.target.value)
          setErr(undefined)
        }}
      />
    </Shell>
  )
}
