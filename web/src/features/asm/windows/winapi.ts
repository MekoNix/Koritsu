/**
 * winapi — сигнатуры функций kernel32, которые зовут консольные программы
 * Windows x64: имена параметров, типы, размеры, смысл.
 *
 * Таблица одна на сайт: её читают «Стек» (подписи параметров перед `call`),
 * «Регистры» и ползунок (что вернул вызов), «Дамп» (буфер текущего вызова),
 * справка и агент. Две копии разошлись бы на первом же `ReadFile`.
 *
 * ── Соглашение Microsoft x64 ────────────────────────────────────────────────
 *
 * Первые четыре параметра — в RCX, RDX, R8, R9 (по порядку, независимо от
 * типа, пока это целые и указатели); пятый и дальше — в стеке по `[RSP+32]`,
 * `[RSP+40]` … на момент `call`. Под четыре регистровых параметра вызывающий
 * всё равно оставляет 32 байта (`shadow space`, `[RSP]…[RSP+31]`): вызываемая
 * функция вправе туда писать. RSP перед `call` кратен 16. Результат — в RAX,
 * портятся RAX RCX RDX R8 R9 R10 R11; стек после возврата снимает вызывающий,
 * поэтому никакого `@N` в имени нет.
 *
 * Параметр типа DWORD занимает в регистре младшие 32 бита: `mov ecx, -11` и
 * `mov rcx, -11` для `GetStdHandle` дают одно и то же.
 */

export type WinType =
  | 'HANDLE'
  | 'DWORD'
  | 'UINT'
  | 'BOOL'
  | 'LPVOID'
  | 'LPCVOID'
  | 'LPDWORD'
  | 'LPOVERLAPPED'
  | 'PCONSOLE_READCONSOLE_CONTROL'
  | 'void'

/** Роль параметра: по ней окна решают, как показать значение. */
export type WinParamRole =
  /** дескриптор (`GetStdHandle`) */
  | 'handle'
  /** адрес буфера данных; длина — в параметре `lenParam` */
  | 'buffer'
  /** число байт или символов */
  | 'count'
  /** адрес DWORD, куда функция запишет результат */
  | 'outCount'
  /** должен быть 0 (NULL) */
  | 'reserved'
  /** просто число */
  | 'value'

export interface WinParam {
  name: string
  type: WinType
  /** Байт в значении: указатели и HANDLE — 8, DWORD/UINT/BOOL — 4. */
  size: 4 | 8
  role: WinParamRole
  /** У буфера — имя параметра с длиной. */
  lenParam?: string
  /** Смысл одной строкой, для подписи и справки. */
  note: string
}

export interface WinFunction {
  dll: 'kernel32'
  name: string
  params: readonly WinParam[]
  returns: { type: WinType; size: 0 | 4 | 8; note: string }
  /** Направление данных — для цвета засечки на дорожке ползунка. */
  io: 'in' | 'out' | 'exit' | 'other'
  /** Не возвращает управление. */
  noreturn?: boolean
  /** Прототип на C, как в документации Windows. */
  proto: string
}

/** Регистры первых четырёх параметров по порядку. */
export const ARG_REGS = ['rcx', 'rdx', 'r8', 'r9'] as const

/** Shadow space: сколько байт над RSP вызывающий оставляет вызываемой функции. */
export const SHADOW_SPACE = 32

/** Регистры, которые вызов вправе испортить; остальные общие (RBX RBP RDI RSI RSP R12–R15) сохраняются. */
export const VOLATILE = ['rax', 'rcx', 'rdx', 'r8', 'r9', 'r10', 'r11'] as const

/** Где лежит параметр номер `i` (с нуля) на момент `call`: регистр или смещение от RSP. */
export function argSlot(i: number): { reg: (typeof ARG_REGS)[number] } | { stack: number } {
  const reg = ARG_REGS[i]
  return reg ? { reg } : { stack: SHADOW_SPACE + 8 * (i - ARG_REGS.length) }
}

const HANDLE_NOTE = 'дескриптор из GetStdHandle'

export const WINAPI: Readonly<Record<string, WinFunction>> = {
  GetStdHandle: {
    dll: 'kernel32',
    name: 'GetStdHandle',
    io: 'other',
    proto: 'HANDLE GetStdHandle(DWORD nStdHandle)',
    params: [{ name: 'nStdHandle', type: 'DWORD', size: 4, role: 'value', note: '-10 ввод, -11 вывод, -12 ошибки' }],
    returns: { type: 'HANDLE', size: 8, note: 'дескриптор; -1 (INVALID_HANDLE_VALUE) — ошибка' },
  },
  WriteFile: {
    dll: 'kernel32',
    name: 'WriteFile',
    io: 'out',
    proto:
      'BOOL WriteFile(HANDLE hFile, LPCVOID lpBuffer, DWORD nNumberOfBytesToWrite, LPDWORD lpNumberOfBytesWritten, LPOVERLAPPED lpOverlapped)',
    params: [
      { name: 'hFile', type: 'HANDLE', size: 8, role: 'handle', note: HANDLE_NOTE },
      { name: 'lpBuffer', type: 'LPCVOID', size: 8, role: 'buffer', lenParam: 'nNumberOfBytesToWrite', note: 'адрес байтов для вывода' },
      { name: 'nNumberOfBytesToWrite', type: 'DWORD', size: 4, role: 'count', note: 'сколько байт вывести' },
      { name: 'lpNumberOfBytesWritten', type: 'LPDWORD', size: 8, role: 'outCount', note: 'адрес DWORD: сколько записано' },
      { name: 'lpOverlapped', type: 'LPOVERLAPPED', size: 8, role: 'reserved', note: 'для консоли — 0' },
    ],
    returns: { type: 'BOOL', size: 4, note: 'не 0 — успех, 0 — ошибка (GetLastError)' },
  },
  ReadFile: {
    dll: 'kernel32',
    name: 'ReadFile',
    io: 'in',
    proto:
      'BOOL ReadFile(HANDLE hFile, LPVOID lpBuffer, DWORD nNumberOfBytesToRead, LPDWORD lpNumberOfBytesRead, LPOVERLAPPED lpOverlapped)',
    params: [
      { name: 'hFile', type: 'HANDLE', size: 8, role: 'handle', note: HANDLE_NOTE },
      { name: 'lpBuffer', type: 'LPVOID', size: 8, role: 'buffer', lenParam: 'nNumberOfBytesToRead', note: 'куда положить прочитанное' },
      { name: 'nNumberOfBytesToRead', type: 'DWORD', size: 4, role: 'count', note: 'размер буфера' },
      { name: 'lpNumberOfBytesRead', type: 'LPDWORD', size: 8, role: 'outCount', note: 'адрес DWORD: сколько прочитано (с \\r\\n)' },
      { name: 'lpOverlapped', type: 'LPOVERLAPPED', size: 8, role: 'reserved', note: 'для консоли — 0' },
    ],
    returns: { type: 'BOOL', size: 4, note: 'не 0 — успех; прочитано 0 байт — ввод кончился' },
  },
  WriteConsoleA: {
    dll: 'kernel32',
    name: 'WriteConsoleA',
    io: 'out',
    proto:
      'BOOL WriteConsoleA(HANDLE hConsoleOutput, const VOID *lpBuffer, DWORD nNumberOfCharsToWrite, LPDWORD lpNumberOfCharsWritten, LPVOID lpReserved)',
    params: [
      { name: 'hConsoleOutput', type: 'HANDLE', size: 8, role: 'handle', note: HANDLE_NOTE },
      { name: 'lpBuffer', type: 'LPCVOID', size: 8, role: 'buffer', lenParam: 'nNumberOfCharsToWrite', note: 'адрес символов' },
      { name: 'nNumberOfCharsToWrite', type: 'DWORD', size: 4, role: 'count', note: 'сколько символов' },
      { name: 'lpNumberOfCharsWritten', type: 'LPDWORD', size: 8, role: 'outCount', note: 'адрес DWORD: сколько выведено' },
      { name: 'lpReserved', type: 'LPVOID', size: 8, role: 'reserved', note: 'должен быть 0' },
    ],
    returns: { type: 'BOOL', size: 4, note: 'не 0 — успех; на перенаправленном выводе — 0' },
  },
  ReadConsoleA: {
    dll: 'kernel32',
    name: 'ReadConsoleA',
    io: 'in',
    proto:
      'BOOL ReadConsoleA(HANDLE hConsoleInput, LPVOID lpBuffer, DWORD nNumberOfCharsToRead, LPDWORD lpNumberOfCharsRead, PCONSOLE_READCONSOLE_CONTROL pInputControl)',
    params: [
      { name: 'hConsoleInput', type: 'HANDLE', size: 8, role: 'handle', note: 'дескриптор из GetStdHandle(-10)' },
      { name: 'lpBuffer', type: 'LPVOID', size: 8, role: 'buffer', lenParam: 'nNumberOfCharsToRead', note: 'куда положить строку' },
      { name: 'nNumberOfCharsToRead', type: 'DWORD', size: 4, role: 'count', note: 'размер буфера в символах' },
      { name: 'lpNumberOfCharsRead', type: 'LPDWORD', size: 8, role: 'outCount', note: 'адрес DWORD: сколько прочитано (с \\r\\n)' },
      { name: 'pInputControl', type: 'PCONSOLE_READCONSOLE_CONTROL', size: 8, role: 'reserved', note: 'обычно 0' },
    ],
    returns: { type: 'BOOL', size: 4, note: 'не 0 — успех' },
  },
  ExitProcess: {
    dll: 'kernel32',
    name: 'ExitProcess',
    io: 'exit',
    noreturn: true,
    proto: 'void ExitProcess(UINT uExitCode)',
    params: [{ name: 'uExitCode', type: 'UINT', size: 4, role: 'value', note: 'код завершения' }],
    returns: { type: 'void', size: 0, note: 'не возвращается' },
  },
  GetLastError: {
    dll: 'kernel32',
    name: 'GetLastError',
    io: 'other',
    proto: 'DWORD GetLastError(void)',
    params: [],
    returns: { type: 'DWORD', size: 4, note: 'код ошибки последнего неудачного вызова' },
  },
}

/**
 * Функция по имени в любом виде, в каком оно встречается: `kernel32.WriteFile`
 * (поле шага `call`), `WriteFile`, `__imp_WriteFile` (ячейка таблицы импорта),
 * `WriteFile@plt`-подобные хвосты отбрасываются. Незнакомая — `null`.
 */
export function winapi(name: string | null | undefined): WinFunction | null {
  if (!name) return null
  let n = name.trim()
  const dot = n.lastIndexOf('.')
  if (dot >= 0) n = n.slice(dot + 1)
  n = n.replace(/^_*imp_+/i, '').replace(/^_+/, '').replace(/@.*$/, '')
  return WINAPI[n] ?? null
}

/** Короткое имя вызова без библиотеки: `kernel32.WriteFile` → `WriteFile`. */
export function apiShortName(call: string): string {
  const dot = call.lastIndexOf('.')
  return dot >= 0 ? call.slice(dot + 1) : call
}
