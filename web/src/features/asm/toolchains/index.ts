/**
 * toolchains — описатель режима программы: всё, чем TASM отличается от MinGW x64
 * там, где окно общее.
 *
 * Окна берут описатель из `useAsm().toolchain`, второго контекста нет. Описатель
 * лёгкий: подсветка и справка грузятся лениво (`language()`, `docs()`), поэтому
 * оба режима можно держать в одном куске сборки.
 *
 * Три окна, у которых сегментная память в самой раскладке (Регистры, Дамп, Стек),
 * описатель не ветвит — у MinGW x64 это отдельные файлы, их подставляет
 * `windows/registry.ts`.
 *
 * Описатели не трогают значения `windows/format.ts` при загрузке модуля — только
 * внутри функций: `format.ts` читает `store.tsx`, а тот — этот файл.
 */
import type { StreamLanguage } from '@codemirror/language'
import type { ReactNode } from 'react'

import type { DocEntry } from '../docs/entries'
import type { AsmMemoryModel, AsmRunSummary, AsmSettings, AsmStep, AsmToolchainId } from '../types'
import { MINGW64 } from './mingw64'
import { TASM } from './tasm'

/** Адрес: `seg = null` — плоская память. */
export interface AsmAddr {
  seg: number | null
  off: number
}

export interface AsmRegGroup {
  id: 'general' | 'index' | 'segment' | 'ip'
  names: readonly string[]
}

export type AsmFlagName = 'OF' | 'DF' | 'IF' | 'TF' | 'SF' | 'ZF' | 'AF' | 'PF' | 'CF'

export interface AsmFlagDef {
  name: AsmFlagName
  /** Номер бита в FLAGS / RFLAGS. */
  bit: number
  /** Подпись `[при 0, при 1]`: у TASM — мнемоники DebugX (`NV`/`OV`), у MinGW x64 — `0`/`1`. */
  label: readonly [string, string]
}

export interface AsmLanguage {
  language: StreamLanguage<unknown>
  spans(text: string): ReactNode
  mnemonicOf(text: string): string | null
}

export interface AsmToolchainDef {
  id: AsmToolchainId
  memory: AsmMemoryModel
  /** Разрядность регистров по умолчанию. */
  bits: 16 | 64
  /** Показывать ли переключатель 16/32 (только TASM). */
  bitsSwitch: boolean
  registers: readonly AsmRegGroup[]
  flags: readonly AsmFlagDef[]
  /** Этапы хода прогона: две ступени сборки и трасса. */
  stages: readonly [string, string, string]
  tools: readonly [string, string]
  /** Ключи i18n: заголовок окна сырого вывода и подпись среды в строке клавиш. */
  titles: { raw: string; env: string }
  language(): Promise<AsmLanguage>
  docs(): Promise<readonly DocEntry[]>
  addr: {
    /** Знаков hex в смещении. */
    width: 4 | 16
    parse(text: string, step: AsmStep | undefined, run: AsmRunSummary | undefined): AsmAddr | null
    fmt(a: AsmAddr): string
    linear(a: AsmAddr): number
    /** Указатель стека шага числом: SP или RSP. По нему «шаг с обходом CALL» ищет возврат. */
    sp(step: AsmStep | undefined): number | null
  }
  /** Засечка на дорожке: `int 21h/20h` у TASM, вызов API у MinGW x64. */
  isSysCall(step: AsmStep): boolean
  buildFlags: {
    keys: readonly [keyof AsmSettings, keyof AsmSettings]
    /** Команды сборки так, как их набирают руками; `base` — имя файла без расширения. */
    preview(s: AsmSettings, base: string): string
  }
}

/** Порядок режимов на странице «Новая программа» и в фильтре списка. */
export const TOOLCHAIN_IDS: readonly AsmToolchainId[] = ['tasm', 'mingw64']

/** Метка Beta у режима — вдобавок к общей метке модуля. */
export const TOOLCHAIN_BETA: Readonly<Record<AsmToolchainId, boolean>> = { tasm: false, mingw64: true }

/** Расширение исходника: для скачивания, открытия с диска и превью команд. */
export const SOURCE_EXT: Readonly<Record<AsmToolchainId, string>> = { tasm: 'asm', mingw64: 's' }

export function isToolchainId(x: unknown): x is AsmToolchainId {
  return x === 'tasm' || x === 'mingw64'
}

export function toolchainDef(id: AsmToolchainId | undefined): AsmToolchainDef {
  return id === 'mingw64' ? MINGW64 : TASM
}

/**
 * Исходник новой программы режима. Служба заводит программу с пустым текстом;
 * страница при первом открытии пустой программы (версия исходника 0) кладёт
 * пример сюда. У TASM примера нет — там пустой лист, как было.
 *
 * Пример MinGW x64 — консольная программа Windows x64 на GAS в Intel-синтаксисе:
 * соглашение Microsoft x64 (параметры в RCX, RDX, R8, R9, пятый — `[rsp+32]`,
 * shadow space 32 байта, RSP кратен 16 перед `call`), вывод через `WriteFile`,
 * подпрограмма с флагами и переходами. Собирается командами из превью
 * «Параметров сборки»; точка входа — начало `.text`.
 */
export const SAMPLE_SOURCE: Readonly<Partial<Record<AsmToolchainId, string>>> = {
  mingw64: `    .intel_syntax noprefix      #включаем режим интеловской нотации без префикса
    .globl  main                #определяем имя точки входа в программу
    .data
    .p2align 4
handle:     .quad   0           #дескриптор консоли (8 байт достаточно)
written:    .quad   0           #сюда WriteFile положит число записанных байт
num1:       .float  -1.4
num2:       .double 101.2
arra:       .space  64
message:    .asciz  "Hello GAS\\n"       #текст выводимого сообщения
    .equ    meslen, .-message-1         #длина без нулевого байта
    .text
main:                           #старт программы
    push    rbp
    mov     rbp, rsp
    sub     rsp, 48             #32 байта shadow space + 8 под 5-й параметр, кратно 16
    #получение дескриптора потока вывода на экран
    mov     rcx, -11            #STD_OUTPUT_HANDLE
    call    GetStdHandle
    mov     [rip+handle], rax
    #тело программы
    mov     al, 0x5A            #байт для преобразования
    call    hextochar           #в AH - символ '5', в AL - символ 'A'
    #вывод строки на экран
    mov     rcx, [rip+handle]           #первый параметр - дескриптор файла
    lea     rdx, [rip+message]          #второй параметр - адрес строки
    mov     r8,  meslen                 #третий параметр - длина строки
    lea     r9,  [rip+written]          #четвёртый параметр - куда записать счётчик
    mov     qword ptr [rsp+32], 0       #пятый параметр - lpOverlapped = NULL
    call    WriteFile                   #вывод на консоль
    add     rsp, 48
    xor     eax, eax            #код возврата 0
    pop     rbp
    ret
#-------------------------------------------------------------------
#Преобразование байта из AL в два символа, его представляющие
#Результат возвращается в AX: AH - старшая цифра, AL - младшая
#-------------------------------------------------------------------
hextochar:
    pushf
    mov     ah, 0               #AX = 00 AL
    shl     ax, 4               #старший полубайт уходит в AH
    shr     al, 4               #младший полубайт возвращается в AL
    cmp     al, 9               #обрабатываем младшую цифру (AL)
    jg      over91
    add     al, '0'
    jmp     next1
over91:
    add     al, 'A'
    sub     al, 10
next1:
    cmp     ah, 9               #обрабатываем старшую цифру (AH)
    jg      over92
    add     ah, '0'
    jmp     next2
over92:
    add     ah, 'A'
    sub     ah, 10
next2:
    popf
    ret
`,
}
