/**
 * entries64 — справка режима MinGW x64: команды x86-64, регистры, адресация,
 * директивы GAS, соглашение Microsoft x64, функции kernel32, сборка `as` и `ld`,
 * типовые ошибки лабораторных и таблица AT&T ↔ Intel.
 *
 * Все примеры — GAS в синтаксисе Intel (`.intel_syntax noprefix`), в том виде,
 * в каком пишутся лабораторные: отступ, команда, операнды, комментарий с `#`.
 * Общих записей с TASM нет: у `mov` в DOS и в Windows x64 разные регистры,
 * размеры, адресация и частые ошибки, и одна запись на два режима путала бы.
 *
 * Сигнатуры kernel32 (параметры, типы, что возвращает) не пишутся здесь второй
 * раз, а берутся из `windows/winapi.ts` — той же таблицы, по которой окно
 * «Стек» подписывает параметры перед `call`. Здесь — только объяснение, пример и
 * частые ошибки.
 *
 * Порядок записей — порядок в списке и старшинство псевдонимов (см. `lookup.ts`).
 */
import { argSlot, WINAPI, type WinFunction } from '../windows/winapi'
import type { DocEntry, DocIoRow } from './entries'

const list: DocEntry[] = []

function add(e: Omit<DocEntry, 'errs' | 'see' | 'kw'> & Partial<Pick<DocEntry, 'errs' | 'see' | 'kw'>>) {
  list.push({
    ...e,
    ex: e.ex || undefined,
    syntax: e.syntax || undefined,
    errs: e.errs ?? [],
    see: e.see ?? [],
    kw: e.kw ?? '',
  })
}

/** Строки кода примера. */
const code = (...lines: string[]) => lines.join('\n')

/* ── команды x86-64 ─────────────────────────────────────────── */

/**
 * Команда: `names` — имена Intel (заголовок и псевдонимы), `att` — имена, которые
 * встречаются только в записи AT&T (`movzbl`, `cqto`): по ним запись находится,
 * но в заголовок они не идут.
 */
function C(
  names: string,
  att: string,
  short: string,
  syntax: string,
  flags: string,
  desc: string,
  ex: string,
  errs: string[],
  see: string[],
  kw: string,
) {
  const a = names.split(' ')
  add({
    id: `x64-${a[0]}`, sec: 'cmd', name: a.join(' / '), alias: [...a, ...(att ? att.split(' ') : [])],
    short, syntax, flags, desc, ex, errs, see, kw,
  })
}

const NOF = '--------'
const ARITH = '*--*****'
const LOGIC = '0--**?*0'
const INCDEC = '*--****-'
const SHIFT = '*--**?**'
const JERR =
  'Для чисел со знаком нужны jg/jl/jge/jle, без знака — ja/jb/jae/jbe. Перепутав, получите неверный переход на отрицательных числах и на байтах от 0x80.'
const OF_ONE = 'OF определён только для сдвига на 1; при сдвиге на большее число он не определён.'

function J(names: string, att: string, cond: string, short: string, desc: string, ex: string, see: string[], kw = '') {
  const a = names.split(' ')
  C(names, att, short, `${a[0]} метка    # ${cond}`, NOF, desc, ex, [JERR], see, `условный переход ${kw}`)
}

C('mov', 'movq movl movw movb movabs', 'пересылка', 'mov приёмник, источник\nmov qword ptr [адрес], число', NOF,
  'Копирует источник в приёмник, источник не меняется. Размер операндов одинаковый и берётся из регистра; у памяти с числом его задаёт `qword/dword/word/byte ptr`. Память в память не пересылается. Запись в 32-битный регистр обнуляет старшие 32 бита 64-битного: `mov eax, -1` даёт RAX = 0x00000000FFFFFFFF, а запись в AX или AL старшие биты не трогает. Число до 32 бит в 64-битный регистр расширяется знаком: `mov rcx, -11` даёт 0xFFFFFFFFFFFFFFF5.',
  code(
    '    mov     rcx, -11            # RCX = 0xFFFFFFFFFFFFFFF5',
    '    mov     [rip+handle], rax   # сохранить RAX в 8-байтную переменную',
    '    mov     rcx, [rip+handle]   # загрузить значение переменной',
    '    mov     qword ptr [rsp+32], 0',
  ),
  ['`mov [rsp+32], 0` не собирается: «ambiguous operand size for `mov`» — у памяти и числа нет размера, нужен `qword ptr`.',
    'В синтаксисе Intel `mov rax, message` без скобок читает 8 байт по адресу метки, а не сам адрес, и требует 32-битного абсолютного адреса. Адрес — `lea rax, [rip+message]`, значение — `mov rax, [rip+message]`.',
    '`mov eax, rbx` — размеры не совпадают: «operand size mismatch for `mov`».',
    '`mov [rip+a], [rip+b]` не бывает: память в память — только через регистр.'],
  ['lea', 'x64-addr-ptr', 'x64-addr-rip', 'x64-reg-zext'], 'копировать загрузить присвоить')
C('lea', 'leaq leal', 'загрузка адреса', 'lea регистр, [адрес]', NOF,
  'Вычисляет адрес операнда и кладёт его в регистр; в память не обращается и флаги не меняет. Адрес переменной в 64-битной программе Windows берётся относительно RIP: `lea rdx, [rip+message]`. С базой и индексом `lea` работает как быстрая арифметика: `lea rax, [rcx+rcx*2]` — RAX = RCX × 3.',
  code(
    '    lea     rdx, [rip+message]  # RDX = адрес строки',
    '    lea     r9, [rip+written]   # R9 = адрес переменной-счётчика',
    '    lea     rax, [rcx+rcx*4]    # RAX = RCX * 5',
  ),
  ['`lea rax, [rip+x]` даёт адрес x, `mov rax, [rip+x]` — 8 байт по этому адресу. Параметры-указатели (`lpBuffer`, `lpNumberOfBytesWritten`) грузятся через `lea`.',
    '`lea rax, 5` не собирается: «operand type mismatch for `lea`» — операнд только адрес в скобках.'],
  ['mov', 'x64-addr-rip', 'x64-addr-sib'], 'адрес указатель')
C('push', 'pushq pushw', 'положить в стек', 'push r64\npush qword ptr [адрес]\npush число', NOF,
  'Уменьшает RSP на 8 и записывает 8 байт по адресу [RSP]. Число до 32 бит расширяется знаком до 64. 32-битного `push` в 64-битном коде нет. `push ax` собирается, но кладёт 2 байта, и стек перестаёт делиться на ячейки по 8.',
  code(
    '    push    rbp                 # RSP -= 8',
    '    mov     rbp, rsp',
    '    ...',
    '    pop     rbp                 # RSP += 8',
  ),
  ['`push eax` не собирается: «operand size mismatch for `push`».',
    'Каждый `push` сдвигает RSP на 8 и меняет выравнивание: лишний `push` перед `call` оставляет RSP не кратным 16.',
    '`push ax` и `pop ax` двигают RSP на 2 — стек съезжает.'],
  ['pop', 'rsp', 'x64-conv-align'], 'стек сохранить')
C('pop', 'popq popw', 'снять со стека', 'pop r64\npop qword ptr [адрес]', NOF,
  'Читает 8 байт из [RSP] в операнд и увеличивает RSP на 8. Снимать нужно в порядке, обратном `push`, и тем же размером.',
  code(
    '    push    rbp',
    '    push    rbx                 # сохраняемый регистр',
    '    ...',
    '    pop     rbx',
    '    pop     rbp                 # именно rbp: 8 байт',
  ),
  ['`pop bp` после `push rbp` собирается без ошибки (байты 66 5D), но снимает 2 байта вместо 8: RSP съезжает на 6, и `ret` берёт адрес возврата со сдвигом.',
    'Лишний или недостающий `pop` перед `ret` — возврат по чужому значению.'],
  ['push', 'ret', 'x64-err-pop-bp'], 'стек восстановить')
C('pushf', 'pushfq', 'RFLAGS в стек', 'pushf', NOF,
  'Кладёт в стек регистр флагов RFLAGS: 8 байт, RSP уменьшается на 8. В 64-битном коде `pushf` и `pushfq` — одна команда (байт 9C).',
  code(
    'hextochar:',
    '    pushf                       # сохранить флаги вызывающего',
    '    ...',
    '    popf',
    '    ret',
  ),
  ['`pushfd` из 32-битного кода не собирается: «invalid instruction suffix for `pushf`».',
    'Между `pushf` и `popf` число `push` и `pop` должно совпадать, иначе `popf` загрузит во флаги чужое значение.'],
  ['popf', 'rflags'], 'сохранить флаги')
C('popf', 'popfq', 'RFLAGS из стека', 'popf', '**-*****',
  'Снимает 8 байт со стека в RFLAGS: CF, PF, AF, ZF, SF, DF, OF и TF принимают сохранённые значения. IF программа пользователя этой командой не меняет.',
  code('    pushf', '    ...', '    popf                        # флаги как до pushf'),
  ['Флаги, выставленные внутри процедуры (итог `cmp`), после `popf` пропадают — вернуть их вызывающему так нельзя.'],
  ['pushf', 'rflags'], 'восстановить флаги')

C('add', 'addq addl addw addb', 'сложение', 'add приёмник, источник', ARITH,
  'Складывает операнды и пишет сумму в приёмник. CF — перенос из старшего бита (переполнение без знака), OF — переполнение со знаком. `add rsp, N` в эпилоге снимает место, выделенное `sub rsp, N`.',
  code(
    "    add     al, '0'             # цифра 0…9 → её символ",
    '    add     rsp, 48             # снять место, выделенное в прологе',
  ),
  ['`add al, …` вместо `add ah, …` — прибавка уходит не в тот байт: у AX старший байт AH, младший AL.',
    '`add [rip+x], 1` без размера не собирается — нужен `qword ptr` (или dword/word/byte).'],
  ['sub', 'inc', 'cf', 'of', 'x64-err-ah-al'], 'сумма плюс прибавить')
C('sub', 'subq subl subw subb', 'вычитание', 'sub приёмник, источник', ARITH,
  'Вычитает источник из приёмника. CF = 1, если был заём: приёмник без знака меньше источника. `sub rsp, N` в прологе резервирует N байт стека под shadow space, параметры с пятого и локальные переменные.',
  code(
    '    sub     rsp, 48             # 32 shadow space + 8 пятый параметр + 8 выравнивание',
    '    sub     al, 10',
  ),
  ['`sub rsp, 56` после `push rbp` оставляет RSP не кратным 16 перед `call`: 8 (адрес возврата) + 8 (RBP) + 56 = 72.',
    'Если нужно только сравнить, не меняя приёмник, — `cmp`.'],
  ['add', 'cmp', 'neg', 'x64-conv-align', 'x64-err-sub56'], 'разность минус отнять')
C('inc', 'incq incl incw incb', 'увеличить на 1', 'inc операнд', INCDEC,
  'Прибавляет 1. CF не меняет.',
  code('    inc     rsi                 # следующий байт строки'),
  ['`inc [rip+count]` без размера не собирается — `inc qword ptr [rip+count]`.'],
  ['dec', 'add'], 'инкремент прибавить единицу')
C('dec', 'decq decl decw decb', 'уменьшить на 1', 'dec операнд', INCDEC,
  'Вычитает 1, CF не меняет. Пара `dec rcx` / `jnz` работает как цикл со счётчиком.',
  code('    dec     rcx', '    jnz     again'),
  [], ['inc', 'sub', 'jne'], 'декремент отнять единицу')
C('neg', 'negq negl negw negb', 'смена знака', 'neg операнд', ARITH,
  'Заменяет операнд на 0 − операнд (дополнительный код). CF = 0, только если операнд был 0.',
  code('    mov     rax, 5', '    neg     rax                 # RAX = 0xFFFFFFFFFFFFFFFB (−5)'),
  ['`neg` — не инверсия битов: инверсия — `not`.'], ['not', 'sub'], 'минус отрицание знак')
C('cmp', 'cmpq cmpl cmpw cmpb', 'сравнение', 'cmp a, b', ARITH,
  'Вычитает b из a и отбрасывает результат — меняются только флаги. Следом ставится условный переход, `setcc` или `cmovcc`: для чисел без знака ja/jb, со знаком jg/jl.',
  code(
    '    cmp     al, 9               # цифра или буква?',
    '    jg      over91',
    "    add     al, '0'",
  ),
  ['Для чисел со знаком jg/jl, без знака ja/jb — перепутав, получите неверный ответ на отрицательных числах.',
    '`cmp 9, al` не собирается: первый операнд не число.',
    '`cmp al, 300` — число не влезает в байт: `as` предупреждает «0x12c shortened to 0x2c» и сравнивает с 0x2C.'],
  ['je', 'jg', 'ja', 'test', 'x64-setcc'], 'сравнить равно больше меньше')
C('test', 'testq testl testw testb', 'проверка битов', 'test a, b', LOGIC,
  'Побитовое И без записи результата — меняются только флаги. `test rcx, rcx` проверяет регистр на ноль и знак, `test al, 1` — младший бит.',
  code('    test    rcx, rcx            # прочитано 0 байт?', '    jz      done'),
  ['После функции с результатом BOOL проверяйте `test eax, eax`: старшую половину RAX функция не обязана обнулять.'],
  ['cmp', 'and', 'je'], 'проверить бит ноль')
C('jmp', 'jmpq', 'безусловный переход', 'jmp метка\njmp регистр\njmp qword ptr [адрес]', NOF,
  'Безусловный переход. `as` сам выбирает короткую форму (2 байта, ±127) или длинную (5 байт, ±2 ГБ) — «переход слишком далеко» в 64-битном коде не бывает. Косвенный переход берёт адрес из регистра или ячейки. Переходник импорта, который `ld` ставит для `call WriteFile`, — это `jmp qword ptr [rip+__imp_WriteFile]`.',
  code('    jmp     next1', '    jmp     rax                 # по адресу из RAX'),
  ['Переход назад без условия выхода — вечный цикл; прогон остановится по лимиту шагов.'],
  ['je', 'call', 'x64-build-ld'], 'переход прыжок goto')
J('je jz', '', 'ZF = 1', 'переход, если равно', 'Переход, если после `cmp` операнды равны или результат равен нулю.',
  code('    cmp     al, 13              # Enter?', '    je      done'), ['jne', 'cmp', 'zf'], 'равно ноль')
J('jne jnz', '', 'ZF = 0', 'переход, если не равно', 'Переход, если операнды не равны или результат не ноль.',
  code('    dec     rcx', '    jnz     next'), ['je', 'cmp', 'zf'], 'не равно не ноль')
J('jg jnle', '', 'ZF = 0 и SF = OF', 'больше (со знаком)', 'Переход, если a > b при сравнении чисел со знаком.',
  code('    cmp     al, 9', '    jg      over91'), ['jge', 'ja', 'cmp'], 'больше знаковое')
J('jge jnl', '', 'SF = OF', 'больше или равно (со знаком)', 'Переход, если a ≥ b для чисел со знаком.',
  code('    cmp     rax, 0', '    jge     non_negative'), ['jg', 'jae'], 'больше или равно знаковое')
J('jl jnge', '', 'SF ≠ OF', 'меньше (со знаком)', 'Переход, если a < b для чисел со знаком.',
  code('    cmp     rax, 0', '    jl      negative'), ['jle', 'jb'], 'меньше знаковое отрицательное')
J('jle jng', '', 'ZF = 1 или SF ≠ OF', 'меньше или равно (со знаком)', 'Переход, если a ≤ b для чисел со знаком.',
  code('    cmp     rcx, 0', '    jle     nothing'), ['jl', 'jbe'], 'меньше или равно знаковое')
J('ja jnbe', '', 'CF = 0 и ZF = 0', 'выше (без знака)', 'Переход, если a > b при сравнении беззнаковых чисел, адресов и кодов символов.',
  code("    cmp     al, 'z'", '    ja      skip'), ['jae', 'jg', 'cmp'], 'больше беззнаковое выше')
J('jae jnb jnc', '', 'CF = 0', 'выше или равно (без знака)', 'Переход, если a ≥ b без знака; та же команда `jnc` — «переноса нет».',
  code("    cmp     al, '0'", '    jae     maybe_digit'), ['jb', 'ja', 'cf'], 'больше или равно беззнаковое нет переноса')
J('jb jnae jc', '', 'CF = 1', 'ниже (без знака)', 'Переход, если a < b без знака; та же команда `jc` — «есть перенос».',
  code("    cmp     al, 'a'", '    jb      skip'), ['jae', 'jl', 'cf'], 'меньше беззнаковое перенос')
J('jbe jna', '', 'CF = 1 или ZF = 1', 'ниже или равно (без знака)', 'Переход, если a ≤ b без знака.',
  code('    cmp     al, 32', '    jbe     control_char'), ['jb', 'jle'], 'меньше или равно беззнаковое')

const SETCC = 'seta setae setb setbe setc sete setg setge setl setle setna setnae setnb setnbe setnc setne setng setnge setnl setnle setno setnp setns setnz seto setp setpe setpo sets setz'
add({
  id: 'x64-setcc', sec: 'cmd', name: 'setcc', alias: ['setcc', ...SETCC.split(' ')], short: 'условие → байт 0 или 1',
  syntax: 'sete  r8 / byte ptr [адрес]\nsetne · setg · setge · setl · setle · seta · setae · setb · setbe · sets · seto …',
  flags: NOF,
  desc: 'Записывает в байт 1, если условие выполнено, иначе 0. Условия те же, что у условных переходов. Приёмник только 8-битный; число в 64-битном регистре получают расширением `movzx eax, al`.',
  ex: code(
    '    cmp     rcx, rdx',
    '    setl    al                  # AL = 1, если RCX < RDX со знаком',
    '    movzx   eax, al             # RAX = 0 или 1',
  ),
  errs: ['`sete eax` не собирается: «operand size mismatch for `sete`» — только байт.',
    '`xor eax, eax` между `cmp` и `setcc` испортит флаги: обнулять регистр нужно до `cmp`.'],
  see: ['cmp', 'movzx', 'x64-cmovcc'], kw: 'условие флаг булево',
})
const CMOVCC = 'cmova cmovae cmovb cmovbe cmovc cmove cmovg cmovge cmovl cmovle cmovna cmovnae cmovnb cmovnbe cmovnc cmovne cmovng cmovnge cmovnl cmovnle cmovno cmovnp cmovns cmovnz cmovo cmovp cmovpe cmovpo cmovs cmovz'
add({
  id: 'x64-cmovcc', sec: 'cmd', name: 'cmovcc', alias: ['cmovcc', ...CMOVCC.split(' ')], short: 'пересылка по условию',
  syntax: 'cmove  r, r/m\ncmovne · cmovg · cmovl · cmova · cmovb …',
  flags: NOF,
  desc: 'Копирует источник в приёмник, только если условие выполнено; иначе приёмник не меняется. У 32-битного приёмника старшая половина 64-битного регистра обнуляется в обоих случаях. 8-битной формы нет, источник — регистр или память.',
  ex: code(
    '    mov     rax, rcx',
    '    cmp     rdx, rcx',
    '    cmovl   rax, rdx            # RAX = меньшее из RCX и RDX',
  ),
  errs: ['`cmovl rax, 5` не собирается: «operand type mismatch for `cmovl`» — число в источнике нельзя.',
    'Источник-память читается и при ложном условии: неверный адрес уронит программу.'],
  see: ['x64-setcc', 'cmp', 'mov'], kw: 'условие минимум максимум',
})

C('shl sal', 'shlq shll shlw shlb salq sall', 'сдвиг влево', 'shl операнд, число\nshl операнд, cl', SHIFT,
  'Сдвиг влево: в младший бит входит 0, старший уходит в CF. Сдвиг на n — умножение без знака на 2ⁿ. Счётчик — число или CL; у 64-битного операнда берутся младшие 6 бит счётчика, у остальных — 5.',
  code(
    '    mov     ah, 0               # AX = 00 AL',
    '    shl     ax, 4               # старший полубайт AL уходит в AH',
  ),
  [OF_ONE, 'Счётчик из другого регистра (`shl rax, bl`) не собирается — только CL.'],
  ['shr', 'sar', 'x64-rol'], 'умножить на 2')
C('shr', 'shrq shrl shrw shrb', 'логический сдвиг вправо', 'shr операнд, число\nshr операнд, cl', SHIFT,
  'Сдвиг вправо: в старший бит входит 0, младший уходит в CF. Деление без знака на 2ⁿ.',
  code('    shr     al, 4               # младший полубайт → старший уходит, AL = 0…15'),
  ['Для отрицательных чисел даёт неверное деление — нужен `sar`.', OF_ONE], ['sar', 'shl'], 'разделить на 2')
C('sar', 'sarq sarl sarw sarb', 'арифметический сдвиг вправо', 'sar операнд, число\nsar операнд, cl', SHIFT,
  'Сдвиг вправо с сохранением знакового бита. Деление со знаком на 2ⁿ с округлением вниз: −1 sar 1 = −1.',
  code('    mov     rax, -8', '    sar     rax, 1              # RAX = −4'),
  [OF_ONE, '`sar` округляет вниз, а `idiv` — к нулю: для −7 результаты −4 и −3.'], ['shr', 'idiv'], 'деление со знаком на 2')
C('rol ror', 'rolq roll rolw rolb rorq rorl rorw rorb', 'циклический сдвиг', 'rol операнд, число\nror операнд, cl', '*------*',
  '`rol` переносит старший бит в младший, `ror` — младший в старший; ушедший бит копируется в CF. SF, ZF, AF и PF не меняются.',
  code('    rol     al, 4               # поменять полубайты местами'),
  [OF_ONE], ['shl', 'shr'], 'вращение')

C('and', 'andq andl andw andb', 'побитовое И', 'and приёмник, маска', LOGIC,
  'Побитовое И: сбрасывает биты, которых нет в маске. OF и CF всегда 0.',
  code('    and     al, 0x0F            # оставить младший полубайт'), [], ['or', 'test'], 'маска сбросить биты')
C('or', 'orq orl orw orb', 'побитовое ИЛИ', 'or приёмник, маска', LOGIC,
  'Побитовое ИЛИ: устанавливает биты маски. OF и CF всегда 0.',
  code('    or      al, 0x20            # заглавная латинская → строчная'), [], ['and', 'xor'], 'установить биты')
C('xor', 'xorq xorl xorw xorb', 'исключающее ИЛИ', 'xor приёмник, маска', LOGIC,
  'Исключающее ИЛИ: инвертирует биты маски. `xor eax, eax` обнуляет весь RAX (запись в 32-битную часть обнуляет старшую половину), на байт короче `xor rax, rax` и ставит ZF = 1 — так в лабе задаётся код возврата 0.',
  code('    xor     eax, eax            # RAX = 0, код возврата 0'),
  ['`xor eax, eax` меняет флаги, `mov eax, 0` — нет.'], ['and', 'or', 'not', 'x64-reg-zext'], 'обнулить инвертировать')
C('not', 'notq notl notw notb', 'инверсия битов', 'not операнд', NOF,
  'Инвертирует все биты. Флаги не меняет.',
  code('    mov     al, 0x0F', '    not     al                  # AL = 0xF0'),
  ['`not` — не смена знака: −x даёт `neg`.'], ['neg', 'xor'], 'инвертировать')

C('mul', 'mulq mull mulw mulb', 'умножение без знака', 'mul r/m', '*--????*',
  'Умножает RAX (EAX, AX, AL — по размеру операнда) на операнд без знака. 8 бит: AX = AL × op. 16: DX:AX. 32: EDX:EAX, старшие половины RAX и RDX обнуляются. 64: RDX:RAX = RAX × op. CF = OF = 1, если старшая половина не ноль.',
  code(
    '    mov     rax, 1000000',
    '    mov     rcx, 3000000',
    '    mul     rcx                 # RDX:RAX = 3 000 000 000 000, RDX = 0',
  ),
  ['`mul` портит RDX — второй параметр вызова: параметры готовят после умножения.',
    '`mul 10` не собирается: операнд — регистр или память; с числом — `imul rax, rax, 10`.'],
  ['imul', 'div', 'rdx'], 'умножить произведение')
C('imul', 'imulq imull imulw imulb', 'умножение со знаком', 'imul r/m            # RDX:RAX = RAX × r/m\nimul r, r/m         # r = r × r/m\nimul r, r/m, число  # r = r/m × число', '*--????*',
  'Умножение со знаком в трёх формах. С одним операндом — как `mul`: результат в RDX:RAX (EDX:EAX, DX:AX, AX). С двумя и тремя — младшая половина произведения в регистр-приёмник того же размера, старшая отбрасывается. CF = OF = 1, если результат со знаком не поместился; SF, ZF, AF, PF не определены.',
  code(
    '    imul    rax, rcx            # RAX = RAX * RCX',
    '    imul    rdx, rdx, 10        # RDX = RDX * 10',
    '    mov     rax, -3',
    '    mov     rcx, 7',
    '    imul    rcx                 # RDX:RAX = −21',
  ),
  ['В формах с двумя и тремя операндами переполнение молча отбрасывается — проверяйте `jo`.',
    '8-битной формы с двумя операндами нет: `imul al, bl` не собирается.'],
  ['mul', 'idiv', 'x64-cqo'], 'умножить со знаком')
C('div', 'divq divl divw divb', 'деление без знака', 'div делитель', '?--?????',
  'Делит без знака. Делитель 64 бит: RDX:RAX / делитель → RAX частное, RDX остаток. 32 бит: EDX:EAX → EAX, EDX. 8 бит: AX → AL, AH. Флаги не определены.',
  code(
    '    mov     rax, 27',
    '    xor     edx, edx            # RDX = 0 перед делением',
    '    mov     rcx, 10',
    '    div     rcx                 # RAX = 2, RDX = 7',
  ),
  ['Деление на 0 — исключение `0xC0000094`, частное не влезает в приёмник — `0xC0000095`; программа падает на этой команде.',
    'Не обнулён RDX — делится огромное RDX:RAX, частное не влезает, то же падение.'],
  ['idiv', 'mul', 'rdx'], 'делить деление частное остаток')
C('idiv', 'idivq idivl idivw idivb', 'деление со знаком', 'idiv делитель', '?--?????',
  'Делит со знаком в тех же регистрах, что `div`. Частное округляется к нулю, остаток имеет знак делимого. Перед делением знак делимого расширяют: `cqo` для RAX, `cdq` для EAX, `cbw` для AL.',
  code(
    '    mov     rax, -27',
    '    cqo                         # RDX:RAX = −27',
    '    mov     rcx, 10',
    '    idiv    rcx                 # RAX = −2, RDX = −7',
  ),
  ['`xor edx, edx` вместо `cqo` на отрицательном делимом даёт огромное положительное RDX:RAX и падение.',
    'Деление на 0 и переполнение частного роняют программу.'],
  ['div', 'x64-cqo', 'imul'], 'делить со знаком')
C('cqo cdq cwd', 'cqto cltd cwtd', 'расширение знака в RDX', 'cqo    # RAX → RDX:RAX\ncdq    # EAX → EDX:EAX\ncwd    # AX → DX:AX', NOF,
  'Размножают знаковый бит аккумулятора в RDX (EDX, DX): 0 для неотрицательного, все единицы для отрицательного. Ставятся перед `idiv`. `cdq` пишет EDX, и старшая половина RDX обнуляется.',
  code('    mov     rax, -100', '    cqo                         # RDX = 0xFFFFFFFFFFFFFFFF', '    idiv    rcx'),
  [], ['idiv', 'x64-cdqe'], 'расширение знака')
C('cdqe cwde cbw', 'cltq cwtl cbtw', 'расширение знака в RAX', 'cdqe   # EAX → RAX\ncwde   # AX → EAX\ncbw    # AL → AX', NOF,
  'Расширяют знаком младшую часть аккумулятора на всю ширину: `cbw` — AL в AX, `cwde` — AX в EAX (старшая половина RAX обнуляется), `cdqe` — EAX в RAX.',
  code('    mov     eax, -5             # RAX = 0x00000000FFFFFFFB', '    cdqe                        # RAX = 0xFFFFFFFFFFFFFFFB'),
  ['`mov eax, …` расширяет нулями: знак отрицательного 32-битного числа теряется, пока не сделан `cdqe`.'],
  ['x64-cqo', 'movsx', 'x64-reg-zext'], 'расширение знака')
C('movzx', 'movzbl movzbw movzwl movzbq movzwq', 'расширение нулями', 'movzx r, r/m8\nmovzx r, r/m16', NOF,
  'Копирует байт или слово в регистр большего размера, старшие биты заполняются нулями. Для 32 → 64 отдельной команды нет: это делает обычный `mov eax, ecx`.',
  code(
    '    movzx   eax, byte ptr [rsi] # RAX = байт по адресу RSI',
    '    movzx   ecx, al',
  ),
  ['`movzx rax, eax` не собирается: «operand size mismatch for `movzx`» — нужен `mov eax, eax`.',
    '`movzx eax, [rsi]` без `byte ptr` — «ambiguous operand size for `movzx`».'],
  ['movsx', 'x64-reg-zext', 'x64-setcc'], 'расширение нулями байт')
C('movsx movsxd', 'movsbl movsbw movswl movsbq movswq movslq', 'расширение знаком', 'movsx r, r/m8\nmovsx r, r/m16\nmovsxd r64, r/m32', NOF,
  '`movsx` копирует байт или слово со знаком в регистр большего размера. `movsxd` — двойное слово в 64-битный регистр (в AT&T `movslq`).',
  code(
    '    movsx   eax, al             # байт со знаком → EAX',
    '    movsxd  rax, dword ptr [rip+n32]',
  ),
  ['`mov eax, ecx` расширяет нулями, а не знаком: −1 станет 4294967295.'],
  ['movzx', 'x64-cdqe'], 'расширение знака')

C('call', 'callq', 'вызов процедуры', 'call метка\ncall регистр\ncall qword ptr [адрес]', NOF,
  'Кладёт в стек 8-байтный адрес следующей команды (RSP −= 8) и переходит. Вызов функции Windows по имени (`call WriteFile`) `ld` направляет на переходник `jmp qword ptr [rip+__imp_WriteFile]`. Трасса показывает вызов kernel32 одним шагом с регистрами после возврата. Перед вызовом по соглашению Microsoft x64 RSP кратен 16, а над ним оставлено 32 байта shadow space.',
  code(
    '    mov     rcx, -11            # STD_OUTPUT_HANDLE',
    '    call    GetStdHandle        # RAX = дескриптор',
    '    mov     [rip+handle], rax',
  ),
  ['Своя процедура, изменившая RSP и не вернувшая его, возвращается `ret` по мусору.',
    'Без shadow space вызванная функция вправе затереть то, что лежит в [RSP]…[RSP+31] у вызывающего.'],
  ['ret', 'x64-conv-shadow', 'x64-conv-align', 'x64-api-writefile'], 'процедура подпрограмма функция вызов api')
C('ret', 'retq', 'возврат', 'ret', NOF,
  'Снимает со стека 8 байт и переходит по ним. Возврат из точки входа (`main`) отдаёт управление Windows, и процесс завершается с кодом из EAX — так же, как при `ExitProcess`.',
  code(
    '    add     rsp, 48',
    '    xor     eax, eax            # код возврата 0',
    '    pop     rbp',
    '    ret',
  ),
  ['Адрес возврата не на вершине стека (после `pop bp`, лишнего `push`, `sub rsp` без `add rsp`) — переход по мусору и падение прямо на `ret`: трасса кончается на этой строке.',
    'Разный размер `sub rsp` и `add rsp` — `pop rbp` и `ret` берут не свои ячейки.'],
  ['call', 'x64-conv-frame', 'x64-err-pop-bp'], 'возврат выход')
C('leave', 'leaveq', 'эпилог одной командой', 'leave', NOF,
  'Равносильна `mov rsp, rbp` и `pop rbp`: снимает кадр, построенный `push rbp` / `mov rbp, rsp`, сколько бы ни было выделено `sub rsp`.',
  code('    leave                       # RSP = RBP, затем pop rbp', '    ret'),
  ['`leave` берёт RSP из RBP — испорченный RBP портит и RSP.'], ['x64-conv-frame', 'ret'], 'эпилог кадр')
C('xchg', 'xchgq xchgl', 'обмен значений', 'xchg a, b', NOF,
  'Меняет местами значения двух операндов. С 32-битными регистрами старшие половины обоих 64-битных обнуляются. С памятью команда медленная (неявная блокировка шины) — для обмена с переменной обычно берут два `mov` через регистр.',
  code('    xchg    rax, rdx'), [], ['mov'], 'поменять местами')
C('nop', 'nopq nopl nopw', 'пустая команда', 'nop', NOF,
  'Ничего не делает: 1 байт 0x90. Такими байтами `as` добивает секцию `.text` до кратной длины — в листинге они стоят в конце последней команды (`C3909090`). Выравнивание кода `.p2align` вставляет многобайтные NOP.',
  code('    nop'), [], ['gas-p2align'], 'пусто выравнивание')
C('int3', '', 'точка останова', 'int3', NOF,
  'Байт 0xCC — ловушка для отладчика. Без отладчика Windows сообщает о необработанном исключении `0x80000003`, и программа завершается.',
  code('    int3                        # остановиться здесь'),
  ['Забытый `int3` роняет программу на машине без отладчика.'], ['call'], 'отладка breakpoint')
C('movsb movsw movsq', 'movsl', 'копирование строки', 'movsb\nrep movsb', NOF,
  'Копирует байт (2, 8 байт у `movsw`, `movsq`) из [RSI] в [RDI] и сдвигает оба указателя. Направление задаёт DF; по соглашению Windows при каждом вызове DF = 0, указатели растут. С префиксом `rep` повторяется RCX раз.',
  code(
    '    lea     rsi, [rip+message]',
    '    lea     rdi, [rip+arra]',
    '    mov     rcx, meslen',
    '    rep     movsb               # RCX = 0, RSI и RDI — за концом строк',
  ),
  ['Без `rep` копируется один байт.', '`movsd` без операндов — строковая команда на 4 байта, а не пересылка `double` (`movsd xmm0, …`).'],
  ['x64-rep', 'x64-stosb', 'rsi', 'rdi'], 'копировать строку память')
C('stosb stosw stosd stosq', 'stosl', 'запись в строку', 'stosb\nrep stosb', NOF,
  'Записывает AL (AX, EAX, RAX) в [RDI] и сдвигает RDI. С `rep` заполняет RCX ячеек одним значением.',
  code(
    '    lea     rdi, [rip+arra]',
    '    xor     eax, eax',
    '    mov     ecx, 64',
    '    rep     stosb               # 64 нулевых байта',
  ),
  [], ['x64-rep', 'x64-movsb', 'rdi'], 'заполнить записать')
C('rep repe repz repne repnz', '', 'префиксы повтора', 'rep команда\nrepe команда\nrepne команда', NOF,
  'Повторяют строковую команду: `rep` — RCX раз, `repe` — пока RCX ≠ 0 и ZF = 1, `repne` — пока RCX ≠ 0 и ZF = 0 (два последних — с `cmpsb` и `scasb`). RCX уменьшается на каждом повторе; при RCX = 0 команда не выполняется ни разу. В пошаговой трассе каждый повтор — отдельный шаг.',
  code('    mov     ecx, 100', '    xor     eax, eax', '    rep     stosb'),
  ['RCX после `rep` равен 0 — если он нужен дальше, сохраните его.'],
  ['x64-movsb', 'x64-stosb', 'rcx'], 'повтор строковые')

C('movss movsd', '', 'пересылка float и double', 'movss xmm, dword ptr [адрес]\nmovsd xmm, qword ptr [адрес]', NOF,
  'Копирует число с плавающей точкой между регистром XMM и памятью или другим XMM: `movss` — 4 байта (`.float`), `movsd` — 8 байт (`.double`). По соглашению Microsoft x64 дробные параметры с первого по четвёртый — в XMM0…XMM3, дробный результат — в XMM0.',
  code(
    '    movss   xmm1, dword ptr [rip+num1]  # XMM1 = −1.4',
    '    movsd   xmm0, qword ptr [rip+num2]  # XMM0 = 101.2',
  ),
  ['`mov rax, [rip+num2]` загружает биты числа как целое: 101.2 превращается в 0x40594CCCCCCCCCCD.',
    '`movsd` без операндов — строковая команда, а не пересылка double.'],
  ['x64-addsd', 'x64-reg-xmm', 'gas-double'], 'дробное плавающая точка sse')
C('addsd subsd mulsd divsd', 'addss subss mulss divss', 'арифметика float и double', 'addsd xmm, xmm/m64\naddss xmm, xmm/m32', NOF,
  'Скалярная арифметика SSE: `…sd` — над double, `…ss` — над float. Результат — в первом операнде. Флаги целых эти команды не меняют; сравнение — `comisd` или `ucomisd`, после него переходы как для беззнаковых: ja, jb, je.',
  code(
    '    movsd   xmm0, qword ptr [rip+num2]',
    '    addsd   xmm0, xmm0          # XMM0 = 202.4',
  ),
  ['`addsd` с 4-байтной `.float` читает мусор: размеры должны совпадать (`addss` для float).'],
  ['x64-movss', 'x64-cvtsi2sd'], 'дробное сложение sse')
C('cvtsi2sd cvttsd2si', 'cvtsi2ss cvttss2si cvtsd2si cvtss2si', 'целое ↔ дробное', 'cvtsi2sd xmm, r/m64\ncvttsd2si r64, xmm/m64', NOF,
  '`cvtsi2sd` переводит целое со знаком в double, `cvttsd2si` — double в целое с отбрасыванием дробной части. `cvtsd2si` (без второго t) округляет по текущему режиму — обычно к ближайшему.',
  code(
    '    mov     rax, 7',
    '    cvtsi2sd xmm0, rax          # XMM0 = 7.0',
    '    cvttsd2si rcx, xmm0         # RCX = 7',
  ),
  [], ['x64-movss', 'x64-addsd'], 'преобразование дробное целое')

/* ── регистры и флаги ────────────────────────────────────── */

function R(key: string, name: string, alias: string[], short: string, desc: string, errs: string[], see: string[], ex: string) {
  add({
    id: `x64-reg-${key}`, sec: 'reg', name, alias, short,
    syntax: alias.join(' · ').toUpperCase(), desc, ex, errs, see, kw: 'регистр',
  })
}

R('rax', 'RAX', ['rax', 'eax', 'ax', 'ah', 'al'], 'аккумулятор, результат',
  'Результат функции по соглашению Microsoft x64: `GetStdHandle` возвращает дескриптор в RAX, `WriteFile` — BOOL в EAX. Неявный операнд `mul`, `div`, `cqo`, `stosb`. Портится любым вызовом. EAX — младшие 32 бита, AX — 16, AL — младший байт, AH — биты 8–15.',
  ['Значение, положенное в RAX до `call`, после вызова потеряно.'], ['x64-conv-ret', 'mul', 'x64-reg-parts'],
  code('    xor     eax, eax            # код возврата 0'))
R('rbx', 'RBX', ['rbx', 'ebx', 'bx', 'bh', 'bl'], 'база, сохраняемый',
  'Регистр общего назначения, сохраняется через вызовы: `WriteFile` его не меняет. Своя функция, которая портит RBX, сохраняет его в прологе и восстанавливает перед `ret`.',
  ['RBX изменён в `main` и не восстановлен перед `ret` — код Windows, вызвавший `main`, вправе на него рассчитывать.'],
  ['x64-conv-volatile', 'push'], code('    push    rbx', '    ...', '    pop     rbx'))
R('rcx', 'RCX', ['rcx', 'ecx', 'cx', 'ch', 'cl'], '1-й параметр, счётчик',
  'Первый параметр вызова: дескриптор у `WriteFile`, номер потока у `GetStdHandle`, код у `ExitProcess`. Счётчик `rep` и `loop`; CL — счётчик сдвигов. Портится вызовом.',
  ['После `call` RCX уже не тот: перед следующим вызовом дескриптор снова грузится из переменной (`mov rcx, [rip+handle]`).'],
  ['x64-conv-args', 'x64-rep', 'shl'], code('    mov     rcx, [rip+handle]   # первый параметр'))
R('rdx', 'RDX', ['rdx', 'edx', 'dx', 'dh', 'dl'], '2-й параметр',
  'Второй параметр вызова: адрес буфера у `WriteFile` и `ReadFile`. Старшая половина произведения `mul`/`imul` и остаток `div`/`idiv`. Портится вызовом.',
  ['`mul` и `div` затирают RDX — второй параметр готовят после арифметики.'],
  ['x64-conv-args', 'mul', 'div'], code('    lea     rdx, [rip+message]  # второй параметр'))
R('rsi', 'RSI', ['rsi', 'esi', 'si', 'sil'], 'источник, сохраняемый',
  'Источник строковых команд ([RSI]). В соглашении Microsoft x64 — сохраняемый регистр; параметры в нём не передаются.',
  ['Параметры в RDI, RSI — это соглашение Linux; Windows ждёт RCX, RDX, R8, R9.'],
  ['x64-movsb', 'x64-conv-volatile'], code('    lea     rsi, [rip+buf]', '    mov     al, [rsi]'))
R('rdi', 'RDI', ['rdi', 'edi', 'di', 'dil'], 'приёмник, сохраняемый',
  'Приёмник строковых команд ([RDI]). Сохраняемый регистр: своя функция, меняющая его, восстанавливает его перед `ret`.',
  ['Параметры в RDI, RSI — это соглашение Linux; Windows ждёт RCX, RDX, R8, R9.'],
  ['x64-stosb', 'x64-conv-volatile'], code('    lea     rdi, [rip+arra]'))
R('rbp', 'RBP', ['rbp', 'ebp', 'bp', 'bpl'], 'указатель кадра',
  'Сохраняемый регистр; по обычаю — база кадра: `push rbp` / `mov rbp, rsp` в прологе, `pop rbp` в эпилоге. Локальные переменные — `[rbp-8]`, `[rbp-16]`…',
  ['`pop bp` вместо `pop rbp` восстанавливает 16 бит и сдвигает RSP на 2 вместо 8.'],
  ['x64-conv-frame', 'x64-err-pop-bp'], code('    push    rbp', '    mov     rbp, rsp'))
R('rsp', 'RSP', ['rsp', 'esp', 'sp', 'spl'], 'указатель стека',
  'Вершина стека. `push` и `call` уменьшают RSP на 8, `pop` и `ret` увеличивают на 8. Перед каждым `call` RSP кратен 16 (последняя hex-цифра — 0), над ним 32 байта shadow space. На входе в функцию, сразу после `call`, последняя hex-цифра RSP — 8.',
  ['RSP после своей процедуры не вернулся к значению до `call` — несимметричные `push`/`pop` или `sub`/`add`.'],
  ['x64-conv-align', 'x64-conv-shadow', 'push'],
  code(
    '                                # вход в main:  RSP = …F78',
    '    push    rbp                 #               RSP = …F70',
    '    mov     rbp, rsp',
    '    sub     rsp, 48             #               RSP = …F40 — кратен 16',
  ))
R('r8', 'R8', ['r8', 'r8d', 'r8w', 'r8b'], '3-й параметр',
  'Третий параметр вызова: длина у `WriteFile`. R8D — младшие 32 бита, R8W — 16, R8B — младший байт. Портится вызовом.',
  [], ['x64-conv-args', 'x64-reg-parts'], code('    mov     r8, meslen          # третий параметр'))
R('r9', 'R9', ['r9', 'r9d', 'r9w', 'r9b'], '4-й параметр',
  'Четвёртый параметр вызова: адрес счётчика у `WriteFile`. Портится вызовом.',
  ['Пятый параметр в регистре не передаётся — только в стеке, `qword ptr [rsp+32]`.'],
  ['x64-conv-args', 'x64-conv-stack'], code('    lea     r9, [rip+written]   # четвёртый параметр'))
R('r10', 'R10 · R11', ['r10', 'r10d', 'r10w', 'r10b', 'r11', 'r11d', 'r11w', 'r11b'], 'рабочие, портятся',
  'Регистры без роли в соглашении; вызов вправе их испортить. После `call` в них может лежать что угодно.',
  [], ['x64-conv-volatile'], '')
R('r12', 'R12…R15', ['r12', 'r13', 'r14', 'r15', 'r12d', 'r13d', 'r14d', 'r15d', 'r12w', 'r13w', 'r14w', 'r15w', 'r12b', 'r13b', 'r14b', 'r15b'], 'сохраняемые',
  'Сохраняются через вызовы, как RBX: в них удобно держать значения, нужные после `call` (счётчик цикла вокруг `WriteFile`). Своя функция, меняющая их, сохраняет их в стеке.',
  [], ['x64-conv-volatile', 'rbx'], code('    push    r12', '    ...', '    pop     r12'))
R('rip', 'RIP', ['rip', 'eip', 'ip'], 'указатель команды',
  'Адрес следующей команды; меняется переходами, `call` и `ret`. Прямо не записывается, но служит базой адресации: `[rip+метка]` — метка относительно конца текущей команды. Так адресуются переменные 64-битной программы Windows.',
  ['`mov rip, rax` не существует — `jmp rax`.'], ['x64-addr-rip', 'jmp'], '')
R('rflags', 'RFLAGS', ['rflags', 'eflags', 'flags'], 'регистр флагов',
  'Используются 9 флагов: CF (бит 0), PF (2), AF (4), ZF (6), SF (7), TF (8), IF (9), DF (10), OF (11); бит 1 всегда 1. Окно регистров показывает флаги по одному, 0 или 1. Например, 0x246 — взведены PF, ZF и IF.',
  [], ['pushf', 'popf', 'zf', 'cf'], code('    pushf', '    pop     rax                 # RAX = RFLAGS'))

function F(name: string, bit: number, short: string, desc: string, see: string[], ex: string) {
  add({
    id: `x64-flag-${name.toLowerCase()}`, sec: 'reg', name, alias: [name.toLowerCase()], short,
    syntax: `бит ${bit} RFLAGS`, desc, ex, see, kw: 'флаг',
  })
}

F('OF', 11, 'переполнение', '1, если результат со знаком не поместился: 0x7F + 1 = 0x80 в байте — 127 + 1 превратилось в −128.', ['add', 'jg', 'imul'],
  code('    mov     al, 0x7F', '    add     al, 1               # OF = 1'))
F('DF', 10, 'направление', '0 — строковые команды идут вперёд, 1 — назад. По соглашению Windows на входе и выходе любой функции DF = 0.', ['x64-movsb', 'x64-conv-volatile'], '')
F('IF', 9, 'разрешение прерываний', 'В программе пользователя всегда 1; `popf` его не меняет.', ['popf'], '')
F('TF', 8, 'пошаговый режим', '1 — после каждой команды процессор останавливается для отладчика. Так снимается пошаговая трасса; программа этот флаг не трогает.', ['rflags'], '')
F('SF', 7, 'знак', 'Копия старшего бита результата: 1 — число отрицательное в знаковом смысле.', ['jl', 'jg', 'cmp'],
  code('    mov     al, 5', '    sub     al, 7               # AL = 0xFE, SF = 1'))
F('ZF', 6, 'ноль', '1, если результат равен нулю. После `cmp a, b` ZF = 1 тогда и только тогда, когда a = b.', ['je', 'jne', 'cmp', 'test'],
  code('    test    rcx, rcx', '    jz      done                # переход при ZF = 1'))
F('AF', 4, 'вспомогательный перенос', 'Перенос из бита 3 в бит 4 — из младшего полубайта. Нужен двоично-десятичной арифметике.', ['add'], '')
F('PF', 2, 'чётность', '1, если в младшем байте результата чётное число единиц.', ['test'], '')
F('CF', 0, 'перенос', 'Перенос или заём из старшего бита — переполнение без знака. Туда же уходит выдвинутый бит сдвигов.', ['jc', 'add', 'shl', 'ja'],
  code('    mov     al, 0xFF', '    add     al, 1               # AL = 0, CF = 1'))

add({
  id: 'x64-reg-zext', sec: 'reg', name: 'запись в 32-битную часть', alias: ['старшие 32 бита', 'zero extension'], short: 'обнуляет старшую половину',
  syntax: 'mov eax, …         # старшие 32 бита RAX = 0\nmov ax, … / mov al, …  # старшие биты не меняются',
  desc: 'Любая команда, записывающая 32-битный регистр (EAX, ECX, R8D…), обнуляет старшие 32 бита 64-битного. Запись в 16- и 8-битные части (AX, AL, R8W, R8B) остальные биты оставляет как были. Поэтому `xor eax, eax` обнуляет весь RAX, `mov eax, ecx` расширяет нулями, а `mov al, 5` при RAX = 0x1234 даёт 0x1205.',
  ex: code(
    '    mov     rax, -1             # RAX = 0xFFFFFFFFFFFFFFFF',
    '    mov     eax, 5              # RAX = 0x0000000000000005',
    '    mov     rax, -1',
    '    mov     al, 5               # RAX = 0xFFFFFFFFFFFFFF05',
  ),
  errs: ['`test rax, rax` после `mov al, …` видит старые байты RAX выше AL.',
    'Отрицательное 32-битное число, загруженное в EAX, в RAX становится большим положительным — нужен `cdqe` или `movsxd`.'],
  see: ['x64-reg-parts', 'xor', 'movzx', 'x64-cdqe'], kw: 'регистр расширение нулями',
})
add({
  id: 'x64-reg-parts', sec: 'reg', name: 'части регистров', alias: ['части регистра', '8 бит', '16 бит', '32 бит'], short: 'EAX, AX, AL, R8D, R8B…',
  syntax: code(
    '64    32     16    8        8 (биты 8–15)',
    'rax   eax    ax    al       ah',
    'rbx   ebx    bx    bl       bh',
    'rcx   ecx    cx    cl       ch',
    'rdx   edx    dx    dl       dh',
    'rsi   esi    si    sil      —',
    'rdi   edi    di    dil      —',
    'rbp   ebp    bp    bpl      —',
    'rsp   esp    sp    spl      —',
    'r8    r8d    r8w   r8b      —',
    '…     …      …     …',
    'r15   r15d   r15w  r15b     —',
  ),
  desc: 'У каждого из 16 регистров есть 32-, 16- и 8-битная часть — младшие биты того же регистра. AH, BH, CH и DH нельзя сочетать в одной команде с частями, которым нужен префикс REX (SIL, DIL, BPL, SPL, R8B…R15B).',
  ex: code('    mov     al, 0x5A            # AL = 0x5A, остальные биты RAX прежние'),
  errs: ['`mov ah, sil` не собирается: «can\'t encode register \'ah\' in an instruction requiring REX prefix».'],
  see: ['x64-reg-zext', 'rax', 'r8'], kw: 'регистр байт слово',
})
add({
  id: 'x64-reg-xmm', sec: 'reg', name: 'XMM0…XMM15', alias: ['xmm0', 'xmm1', 'xmm2', 'xmm3', 'xmm4', 'xmm5', 'xmm6', 'xmm7', 'xmm', 'sse'], short: 'регистры SSE',
  desc: '16 регистров по 128 бит для float и double. XMM0…XMM3 — дробные параметры вызова, XMM0 — дробный результат. XMM0…XMM5 портятся вызовом, XMM6…XMM15 сохраняются.',
  see: ['x64-movss', 'x64-conv-volatile'], kw: 'регистр дробное плавающая точка',
})
add({
  id: 'x64-reg-seg', sec: 'reg', name: 'CS DS SS ES FS GS', alias: ['cs', 'ds', 'ss', 'es', 'fs', 'gs'], short: 'сегментные регистры',
  desc: 'В 64-битной программе память плоская: CS, DS, SS и ES в адресации не участвуют, программа их не загружает. GS указывает на блок потока Windows (TEB). Окно регистров показывает их свёрнутыми.',
  errs: ['Записи TASM вроде `mov ax, @data` / `mov ds, ax` здесь не нужны и не собираются.'],
  see: ['x64-addr-flat'], kw: 'сегмент регистр',
})

/* ── адресация ───────────────────────────────────────────── */

function A(key: string, name: string, alias: string[], short: string, syntax: string, desc: string, ex: string, errs: string[], see: string[], kw: string) {
  add({ id: `x64-addr-${key}`, sec: 'addr', name, alias, short, syntax, desc, ex, errs, see, kw })
}

A('rip', '[rip+метка]', ['[rip+метка]', 'rip+', 'rip-relative', 'относительная адресация'], 'адрес относительно RIP',
  'mov регистр, [rip+метка]         # значение\nlea регистр, [rip+метка]         # адрес\nmov qword ptr [rip+метка], число',
  'Основной способ обратиться к переменной в 64-битной программе. `as` пишет в команду 32-битное смещение метки от конца этой команды, `ld` его вычисляет, поэтому в листинге оно стоит нулями (`48890500 000000`). Такой код работает при любой базе образа; абсолютный 32-битный адрес в образ Windows x64, лежащий выше 4 ГБ, не помещается.',
  code(
    '    mov     [rip+handle], rax   # записать',
    '    mov     rcx, [rip+handle]   # прочитать',
    '    lea     rdx, [rip+message]  # взять адрес',
  ),
  ['`mov rax, [handle]` и `mov rax, handle` без `rip` просят абсолютный 32-битный адрес — `ld` откажет: «relocation truncated to fit».',
    'У RIP-адресации нет индекса: `[rip+arra+rsi*8]` не собирается («is not a valid base/index expression») — адрес массива сначала грузится в регистр.'],
  ['lea', 'x64-addr-abs', 'x64-addr-sib'], 'адрес переменная')
A('base', '[rsp+32]', ['[rsp+32]', '[rbp-8]', 'база+смещение'], 'регистр плюс смещение',
  '[регистр]\n[регистр+смещение]\n[регистр-смещение]',
  'Адрес — значение регистра плюс число. Параметры с пятого лежат в `[rsp+32]`, `[rsp+40]`… в момент `call`; локальные переменные — в `[rbp-8]`, `[rbp-16]`. Смещение в байтах: соседние 8-байтные ячейки — через 8.',
  code(
    '    mov     qword ptr [rsp+32], 0   # пятый параметр',
    '    mov     [rbp-8], rax            # локальная переменная',
  ),
  ['`[rsp+31]` вместо `[rsp+32]` — пятый параметр ложится со сдвигом на байт, и функция читает смесь чужих байтов.'],
  ['x64-conv-stack', 'x64-addr-ptr', 'rsp'], 'адрес стек параметр')
A('sib', '[rbx+rsi*8+16]', ['[rbx+rsi*8+16]', 'масштаб', 'индекс', 'sib'], 'база, индекс, масштаб',
  '[база+индекс*масштаб+смещение]      # масштаб 1, 2, 4, 8',
  'Полная форма адреса: база и индекс — 64-битные регистры, масштаб 1, 2, 4 или 8 (размер элемента), смещение — число. Элемент i массива 8-байтных чисел — `[rbx+rsi*8]`, где RBX — адрес начала.',
  code(
    '    lea     rbx, [rip+arra]     # адрес начала массива',
    '    xor     esi, esi            # индекс 0',
    '    mov     qword ptr [rbx+rsi*8], 7',
    '    mov     rax, [rbx+rsi*8+16] # элемент с индексом i + 2',
  ),
  ['Масштаб только 1, 2, 4, 8: `[rbx+rsi*3]` не собирается.', 'RSP не бывает индексом.'],
  ['x64-addr-rip', 'lea'], 'массив индекс адрес')
A('ptr', 'qword/dword/word/byte ptr', ['ptr', 'qword', 'dword', 'word', 'byte', 'qword ptr', 'dword ptr', 'word ptr', 'byte ptr'], 'размер ячейки',
  'qword ptr [адрес]   # 8 байт\ndword ptr [адрес]   # 4\nword ptr [адрес]    # 2\nbyte ptr [адрес]    # 1',
  'Задаёт размер операнда в памяти, когда его не из чего взять: число в память (`mov qword ptr [rsp+32], 0`), `inc`, `neg`, `push` ячейки, источник `movzx`. В AT&T то же выражается суффиксом команды: `movq $0, 32(%rsp)`.',
  code(
    '    mov     qword ptr [rsp+32], 0',
    '    inc     byte ptr [rip+count]',
    '    movzx   eax, byte ptr [rsi]',
  ),
  ['Без размера `as` пишет «ambiguous operand size for `mov`».',
    '`dword ptr [rsp+32], 0` для 8-байтного параметра записывает 4 байта — старшие остаются от прошлого.'],
  ['mov', 'x64-att'], 'размер qword dword')
A('abs', 'метка без rip', ['offset', 'абсолютный адрес', '[метка]'], 'абсолютный адрес и константа',
  'mov rax, message        # 8 байт по абсолютному адресу\nmov rax, offset message # адрес числом\nmov r8, meslen          # константа .equ — число',
  'В синтаксисе Intel у GAS имя переменной без скобок — содержимое памяти по её абсолютному адресу: `mov rax, message` читает 8 байт, как `mov rax, [message]`, а `offset message` — сам адрес числом. Обе записи требуют 32-битного абсолютного адреса, а образ Windows x64 грузится с базы 0x140000000, и `ld` отвечает «relocation truncated to fit». Имя константы `.equ` без скобок — число: `mov r8, meslen` грузит длину.',
  code(
    '    mov     r8, meslen          # .equ — число',
    '    lea     rdx, [rip+message]  # адрес строки',
    '    mov     rax, [rip+handle]   # значение переменной',
  ),
  ['Адрес переменной в 64-битной программе — только `lea регистр, [rip+метка]`.'],
  ['x64-addr-rip', 'gas-equ', 'x64-build-reloc'], 'адрес offset константа')
A('flat', 'плоская память', ['плоская память', 'image base', 'база образа', 'секции'], 'образ и секции',
  'база образа  0x0000000140000000\n.text        0x0000000140001000\n.data        следующая страница',
  'Адрес — одно 64-битное число, сегментов нет. `ld` кладёт образ по базе 0x140000000: заголовки, затем секции с шагом 0x1000 — `.text` с 0x140001000, `.data` дальше. Стек и блоки системы — в отдельных областях, их адреса к базе не привязаны.',
  '', [], ['x64-reg-seg', 'gas-text', 'gas-data'], 'память адрес секция')

/* ── директивы GAS ───────────────────────────────────────── */

function G(names: string, key: string, short: string, syntax: string, desc: string, ex: string, errs: string[], see: string[], kw: string) {
  const a = names.split(' ')
  add({ id: `gas-${key}`, sec: 'gas', name: a.join(' / '), alias: a, short, syntax, desc, ex, errs, see, kw })
}

const HEADER = code(
  '    .intel_syntax noprefix',
  '    .globl  main',
  '    .data',
  '    .p2align 4',
  'handle:     .quad   0',
  'message:    .asciz  "Hello GAS\\n"',
  '    .equ    meslen, .-message-1',
  '    .text',
  'main:',
)

G('.intel_syntax .att_syntax', 'syntax', 'выбор синтаксиса', '.intel_syntax noprefix\n.att_syntax prefix',
  'Переключает синтаксис до конца файла или до следующего переключения. `noprefix` — регистры без `%`, как в лабе: `mov rax, [rip+x]`. Без директивы `as` читает AT&T: `movq x(%rip), %rax`.',
  HEADER,
  ['Без `.intel_syntax noprefix` Intel-запись не собирается: на `mov rax, rbx` `as` отвечает «operand size mismatch for `mov`».',
    '`.intel_syntax` без `noprefix` требует `%` перед регистрами.'],
  ['x64-att', 'gas-comment'], 'intel att синтаксис noprefix')
G('.globl .global', 'globl', 'глобальное имя', '.globl имя',
  'Делает метку видимой для `ld` и других объектных файлов. Без флага `-e` `ld` ищет точку входа `mainCRTStartup` и, не найдя, начинает с начала `.text` — там в лабе и стоит `main`. С флагом `-e main` точка входа — эта метка, и она должна быть глобальной.',
  code('    .globl  main', '    .text', 'main:'),
  ['Точка входа без `-e` — первая команда секции `.text`, какая бы метка ни стояла у `.globl`: процедура, поставленная выше `main`, выполнится первой.'],
  ['x64-build-entry', 'gas-text'], 'точка входа глобальный символ')
G('.text', 'text', 'секция кода', '.text',
  'Дальше идут команды. В образе — секция с правом выполнения.',
  code('    .text', 'main:', '    push    rbp'),
  ['Команды в `.data` собираются, но выполнять их Windows не даст — падение на первой же.'],
  ['gas-data', 'x64-addr-flat'], 'код секция')
G('.data', 'data', 'секция данных', '.data',
  'Переменные с начальными значениями, доступные на чтение и запись.',
  code('    .data', 'handle:     .quad   0', 'written:    .quad   0'),
  [], ['gas-bss', 'gas-rdata', 'gas-quad'], 'данные переменные секция')
G('.bss', 'bss', 'неинициализированные данные', '.bss',
  'Место под переменные без содержимого в файле: при загрузке заполнено нулями. Внутри — только `.space`/`.skip` с нулём.',
  code('    .bss', 'buf:    .space  256'),
  ['`.quad 5` в `.bss` не собирается: «attempt to store non-zero value in section `.bss`».'],
  ['gas-data', 'gas-space'], 'буфер нули секция')
G('.section', 'rdata', 'именованная секция', '.section .rdata',
  '`.section .rdata` — данные только для чтения: строки и таблицы, которые программа не меняет. Запись туда — исключение `0xC0000005` (нарушение доступа).',
  code('    .section .rdata', 'hello:  .ascii  "Hello\\r\\n"', '    .equ    hello_len, .-hello'),
  ['Переменная, в которую пишет `WriteFile` (счётчик), не может лежать в `.rdata`.'],
  ['gas-data', 'gas-text'], 'секция константы только чтение')
G('.p2align .balign .align', 'p2align', 'выравнивание', '.p2align n\n.balign байт',
  'Выравнивает следующий байт на границу 2ⁿ: `.p2align 4` — кратно 16, `.p2align 3` — кратно 8. В данных дополняет нулями, в коде — командами NOP. `.balign 16` — то же, но число в байтах. `.align` у разных целей понимается по-разному, надёжнее `.p2align` или `.balign`.',
  code('    .data', '    .p2align 4                  # следующая переменная — по адресу, кратному 16', 'handle:     .quad   0'),
  ['Выравнивание действует только на следующий байт: `.double` сразу за `.float` снова стоит невыровненным.'],
  ['gas-data', 'nop'], 'выравнивание align')
G('.byte', 'byte', '1 байт', '.byte значение[, …]',
  'По байту на значение. Символ в кавычках — его код.',
  code("digits: .byte   '0', '1', 0x0A, 255"), [], ['gas-ascii', 'gas-short'], 'байт данные')
G('.short .word .value', 'short', '2 байта', '.short значение[, …]',
  '16-битные значения младшим байтом вперёд. `.word` у x86 — тоже 2 байта.',
  code('ports:  .short  80, 443'), [], ['gas-byte', 'gas-long'], 'слово 16 бит данные')
G('.long .int', 'long', '4 байта', '.long значение[, …]',
  '32-битные значения (DWORD). Счётчик `lpNumberOfBytesWritten` у `WriteFile` — DWORD, ему хватает `.long`; `.quad` тоже годится — старшие 4 байта останутся нулями.',
  code('count:  .long   0'),
  ['`mov rax, [rip+count]` у `.long` захватывает 4 чужих байта следом — читайте `mov eax, [rip+count]`.'],
  ['gas-quad', 'gas-short'], 'двойное слово 32 бит dword')
G('.quad', 'quad', '8 байт', '.quad значение[, …]',
  '64-битные значения: указатели, дескрипторы, переменные для 64-битных регистров. `.quad 0x1122334455667788` лежит в памяти байтами 88 77 66 55 44 33 22 11.',
  code('handle:     .quad   0           # дескриптор консоли', 'written:    .quad   0'),
  ['Переменная `.long`, прочитанная в 64-битный регистр, захватывает 4 чужих байта.'],
  ['gas-long', 'gas-octa', 'mov'], 'qword 64 бит данные')
G('.octa', 'octa', '16 байт', '.octa значение',
  '128-битное целое, младшая половина первой. Встречается в задачах на длинную арифметику: младшие 8 байт по адресу метки, старшие — через 8.',
  code('big:    .octa   0x112233445566778899AABBCCDDEEFF00'), [], ['gas-quad'], '128 бит длинное')
G('.float .single', 'float', '4 байта IEEE', '.float число',
  'Число с плавающей точкой одинарной точности. `.float -1.4` даёт байты 33 33 B3 BF (0xBFB33333).',
  code('num1:       .float  -1.4'),
  ['`.float` не выравнивает: следующая директива стоит сразу за 4 байтами.'],
  ['gas-double', 'x64-movss'], 'дробное float')
G('.double', 'double', '8 байт IEEE', '.double число',
  'Число с плавающей точкой двойной точности. `.double 101.2` даёт байты CD CC CC CC CC 4C 59 40 (0x40594CCCCCCCCCCD).',
  code('num2:       .double 101.2'),
  ['Сразу за `.float` число стоит по смещению, не кратному 8 (в лабе num2 — по +0x14); для SSE-команд с выравниванием поставьте `.p2align 3`.'],
  ['gas-float', 'x64-movss'], 'дробное double')
G('.ascii', 'ascii', 'строка без нуля', '.ascii "текст"',
  'Байты строки без завершающего нуля. Экранирование как в C: `\\n` — 10, `\\r` — 13, `\\t`, `\\\\`, `\\"`.',
  code('prompt: .ascii  "Enter: "', '    .equ    plen, .-prompt       # длина без -1'),
  ['Длина `.ascii` — `.-метка`, без вычитания единицы: нуля в конце нет.'],
  ['gas-asciz', 'gas-dot'], 'строка текст')
G('.asciz .string', 'asciz', 'строка с нулём', '.asciz "текст"',
  'Строка и байт 0 в конце. Длина строки для `WriteFile` без нуля — `.-метка-1` сразу после строки.',
  code('message:    .asciz  "Hello GAS\\n"', '    .equ    meslen, .-message-1'),
  ['`.equ meslen, .-message` после `.asciz` включает нулевой байт — выводится лишний NUL.',
    'Кириллица в строке — это байты UTF-8 исходника: по 2 байта на букву.'],
  ['gas-ascii', 'gas-dot', 'x64-err-meslen'], 'строка текст нуль')
G('.space .skip .zero', 'space', 'резерв байтов', '.space n[, значение]',
  'n байт, заполненных нулями или значением. `arra: .space 64` — буфер на 64 байта.',
  code('arra:       .space  64', 'buf:        .space  256, 0'),
  ['Буфер меньше, чем число байт, переданное в `ReadFile`, — лишние байты затрут соседние переменные.'],
  ['gas-bss', 'x64-api-readfile'], 'буфер массив резерв')
G('.equ .set =', 'equ', 'константа', '.equ имя, выражение\nимя = выражение',
  'Имя для числа; память не занимает. В выражении можно брать `.` и метки: `.equ meslen, .-message-1`. `.set` и `=` — то же, значение можно переопределить ниже по тексту.',
  code('    .equ    STD_OUTPUT_HANDLE, -11', '    mov     rcx, STD_OUTPUT_HANDLE'),
  ['В синтаксисе Intel константа без скобок — число, а метка переменной без скобок — память: `.equ` и `.quad` не взаимозаменяемы.'],
  ['gas-dot', 'x64-addr-abs'], 'константа')
add({
  id: 'gas-dot', sec: 'gas', name: '.', alias: ['.', '.-', 'счётчик адреса'], short: 'текущий адрес',
  syntax: '.-метка',
  desc: 'Точка — адрес места, где сейчас стоит `as` в текущей секции. `.-message` сразу после строки — её длина в байтах. Выражение считается там, где записано: `.equ`, поставленная ниже другой директивы данных, посчитает и её.',
  ex: code('message:    .asciz  "Hello GAS\\n"', '    .equ    meslen, .-message-1     # 11 байт строки минус нуль = 10'),
  errs: ['`.equ` ниже следующей переменной — в длину попадает и эта переменная.'],
  see: ['gas-equ', 'gas-asciz', 'x64-err-meslen'], kw: 'длина строки счётчик',
})
add({
  id: 'gas-label', sec: 'gas', name: 'метка:', alias: ['метка', 'label'], short: 'имя адреса',
  syntax: 'имя:\nимя:  .quad 0\n1:    … jmp 1b / jmp 1f',
  desc: 'Имя с двоеточием — адрес следующего байта в текущей секции. Регистр букв в именах различается. Имена `.L…` — локальные, в таблицу символов не попадают. Числовые метки `1:` можно повторять; `1b` — ближайшая такая выше, `1f` — ниже.',
  ex: code('over91:', "    add     al, 'A'", '    sub     al, 10'),
  errs: ['`hexToChar` и `hextochar` — разные имена: `ld` не найдёт одно по другому.'],
  see: ['gas-globl', 'gas-comment'], kw: 'метка имя символ',
})
add({
  id: 'gas-comment', sec: 'gas', name: '# и ;', alias: ['#', ';', '/*', 'комментарий'], short: 'комментарий и разделитель',
  syntax: '# комментарий до конца строки\n/* комментарий блоком */\nкоманда ; команда      # ; разделяет команды',
  desc: 'У GAS для x86 комментарий начинается с `#` в любом месте строки или записывается блоком `/* … */`. Точка с запятой — разделитель команд на одной строке и в Intel-, и в AT&T-синтаксисе: `mov rax, 1 ; mov rbx, 2` — две команды.',
  ex: code('    mov     rcx, -11            # STD_OUTPUT_HANDLE'),
  errs: ['`; комментарий` по привычке TASM — текст после `;` читается как команда: «no such instruction», для кириллицы «invalid character … in mnemonic».'],
  see: ['gas-syntax', 'x64-build-nosuch'], kw: 'комментарий точка с запятой решётка',
})

/* ── соглашение Microsoft x64 ────────────────────────────── */

function V(key: string, name: string, alias: string[], short: string, syntax: string, desc: string, ex: string, errs: string[], see: string[], kw: string) {
  add({ id: `x64-conv-${key}`, sec: 'conv', name, alias, short, syntax, desc, ex, errs, see, kw: `соглашение о вызовах abi ${kw}` })
}

const WRITEFILE_CALL = code(
  '    mov     rcx, [rip+handle]           # 1: hFile',
  '    lea     rdx, [rip+message]          # 2: lpBuffer',
  '    mov     r8, meslen                  # 3: nNumberOfBytesToWrite',
  '    lea     r9, [rip+written]           # 4: lpNumberOfBytesWritten',
  '    mov     qword ptr [rsp+32], 0       # 5: lpOverlapped = NULL',
  '    call    WriteFile                   # EAX ≠ 0 — успех',
)

V('args', 'параметры: RCX, RDX, R8, R9', ['параметры', 'rcx rdx r8 r9', 'microsoft x64', 'fastcall', 'соглашение'], 'где лежат параметры',
  code(
    'параметр   целое, указатель   дробное',
    '1          RCX                XMM0',
    '2          RDX                XMM1',
    '3          R8                 XMM2',
    '4          R9                 XMM3',
    '5          [RSP+32]',
    '6          [RSP+40]',
    'n ≥ 5      [RSP+32+8·(n−5)]',
  ),
  'Соглашение Microsoft x64 — единственное для 64-битных функций Windows. Первые четыре параметра — в регистрах по номеру, остальные — в стеке над shadow space в момент `call`. Параметр DWORD занимает младшие 32 бита регистра: `mov ecx, -11` и `mov rcx, -11` для `GetStdHandle` равносильны. Стек после вызова снимает вызывающий, декораций `@N` в именах нет.',
  WRITEFILE_CALL,
  ['Параметры в RDI, RSI, RDX, RCX — соглашение Linux: Windows прочитает мусор.',
    'Параметры через `push` не передают: `push` сдвигает RSP, и пятый параметр оказывается не в `[rsp+32]`.'],
  ['x64-conv-stack', 'x64-conv-shadow', 'x64-conv-ret', 'x64-api-writefile'], 'параметры регистры')
V('stack', 'параметры с пятого', ['пятый параметр', '5-й параметр', 'параметры в стеке'], '[RSP+32], [RSP+40]…',
  'перед call:  [RSP+32]  5-й параметр\n             [RSP+40]  6-й параметр\nвнутри:      [RSP+40]  5-й (сдвиг на адрес возврата)',
  'Пятый параметр лежит в `[rsp+32]` в момент `call`, шестой — в `[rsp+40]`. Место под них резервируется в прологе вместе с shadow space (`sub rsp, 48` — 32 + 8 + 8 на выравнивание), значение пишется `mov qword ptr [rsp+32], …` прямо перед вызовом. Внутри вызванной функции всё сдвинуто на 8: адрес возврата лёг сверху.',
  code('    sub     rsp, 48             # в прологе', '    ...', '    mov     qword ptr [rsp+32], 0   # перед call', '    call    WriteFile'),
  ['`[rsp+31]` — сдвиг на байт, параметр читается смешанным с соседним.',
    '`mov [rsp+32], r9` кладёт в пятый параметр значение R9 (адрес счётчика), а не 0.',
    '`sub rsp, 32` без места под пятый параметр: `[rsp+32]` — уже ячейка с сохранённым RBP.'],
  ['x64-conv-args', 'x64-addr-base', 'x64-err-rsp31'], 'стек пятый параметр')
V('shadow', 'shadow space', ['shadow space', 'home space', '32 байта', 'теневое пространство'], '32 байта для вызываемой функции',
  'перед call:  [RSP]…[RSP+31]  shadow space\n             [RSP+32]        5-й параметр\nпосле call:  [RSP]           адрес возврата\n             [RSP+8]…[RSP+39] shadow space',
  'Перед каждым вызовом вызывающий оставляет 32 байта сразу над RSP — даже если параметров меньше четырёх или нет совсем (`GetLastError`). Вызываемая функция вправе сохранить туда RCX, RDX, R8, R9 или использовать их как рабочее место. Место выделяется один раз в прологе (`sub rsp, 32` и больше) и служит всем вызовам функции.',
  code('main:', '    push    rbp', '    mov     rbp, rsp', '    sub     rsp, 48             # shadow space — до первого call', '    mov     rcx, -11', '    call    GetStdHandle'),
  ['Нет `sub rsp` перед `call` — в [RSP]…[RSP+31] лежат сохранённый RBP и адрес возврата из `main`, и функция вправе их затереть. Программа может работать и падать не всегда: зависит от того, пишет ли функция в эти байты.',
    'Место под shadow space выделено после первого `call` — первый вызов идёт без него.'],
  ['x64-conv-align', 'x64-conv-frame', 'x64-err-noshadow'], 'shadow space стек')
V('align', 'выравнивание на 16', ['выравнивание', 'кратно 16', 'alignment'], 'RSP кратен 16 перед call',
  'перед call:       RSP mod 16 = 0   (последняя hex-цифра 0)\nна входе функции: RSP mod 16 = 8   (последняя hex-цифра 8)',
  'Перед каждым `call` RSP кратен 16. На входе в функцию, сразу после `call`, RSP ≡ 8 (mod 16): адрес возврата занял 8 байт. Пролог возвращает кратность: `push rbp` (+8) и `sub rsp, N` с N, кратным 16. Каждый дополнительный `push` сдвигает ещё на 8 — его компенсируют лишние 8 байт в `sub`. Проверка по трассе — последняя hex-цифра RSP на строке `call`.',
  code(
    '                                # вход в main:  RSP = …F78  (≡ 8)',
    '    push    rbp                 #               RSP = …F70  (≡ 0)',
    '    mov     rbp, rsp',
    '    sub     rsp, 48             #               RSP = …F40  (≡ 0) — можно call',
  ),
  ['`sub rsp, 56` после `push rbp` — RSP ≡ 8 перед `call`. Функции Windows, использующие выровненные SSE-команды, падают внутри вызова; остальные работают — ошибка плавающая.',
    'Своя процедура без `push rbp` вызывает API с RSP ≡ 8.'],
  ['rsp', 'x64-conv-frame', 'x64-err-sub56'], 'выравнивание стек 16')
V('volatile', 'портящиеся и сохраняемые', ['volatile', 'non-volatile', 'сохраняемые регистры', 'портятся'], 'что переживает call',
  'портятся:     RAX RCX RDX R8 R9 R10 R11, XMM0–XMM5, флаги\nсохраняются:  RBX RBP RDI RSI RSP R12–R15, XMM6–XMM15',
  'После любого `call` значения в портящихся регистрах считаются потерянными: после `WriteFile` в RCX, RDX, R8…R11 трасса показывает другие числа. Нужное после вызова держат в сохраняемых регистрах или переменных. Своя функция, меняющая сохраняемый регистр, сохраняет его в прологе и восстанавливает перед `ret`. DF на входе и выходе равен 0.',
  code('    mov     r12, rcx            # счётчик переживёт call', '    call    WriteFile', '    dec     r12'),
  ['Счётчик цикла в RCX вокруг `call WriteFile` — после вызова он другой; нужен RBX или R12.',
    'Дескриптор, оставленный в RAX, пропадает на следующем вызове — его сохраняют в переменную.'],
  ['rbx', 'r12', 'x64-conv-args'], 'сохраняемые регистры')
V('ret', 'результат в RAX', ['результат', 'возвращаемое значение', 'return'], 'что возвращает функция',
  'целое, указатель, HANDLE  RAX\nBOOL, DWORD              EAX\nfloat, double            XMM0',
  'Результат — в RAX; у BOOL и DWORD значимы младшие 32 бита (EAX). Дробный — в XMM0. Возврат из `main` — код завершения процесса.',
  code('    call    WriteFile', '    test    eax, eax            # BOOL: 0 — ошибка', '    jz      failed'),
  ['`test rax, rax` после функции с BOOL проверяет и старшую половину, которую функция не обязана обнулять.'],
  ['rax', 'x64-api-getlasterror'], 'результат возврат')
V('frame', 'пролог и эпилог', ['пролог', 'эпилог', 'кадр', 'prologue', 'epilogue'], 'рамка функции',
  code(
    '    push    rbp                 # сохранить RBP; RSP ≡ 0',
    '    mov     rbp, rsp            # база кадра',
    '    sub     rsp, 48             # shadow space + параметры + локальные, кратно 16',
    '    ...',
    '    add     rsp, 48             # или mov rsp, rbp',
    '    pop     rbp',
    '    ret',
  ),
  'Пролог сохраняет RBP, делает его базой кадра и резервирует место в стеке: 32 байта shadow space, место под параметры с пятого у самого длинного вызова и локальные переменные, всё с округлением так, чтобы RSP стал кратен 16. Эпилог снимает место и восстанавливает RBP в обратном порядке; число у `sub` и `add` одно и то же.',
  code('main:', '    push    rbp', '    mov     rbp, rsp', '    sub     rsp, 48', '    ...', '    add     rsp, 48', '    xor     eax, eax', '    pop     rbp', '    ret'),
  ['`add rsp, 40` против `sub rsp, 48` — `pop rbp` снимет не то, `ret` уйдёт по мусору.', '`pop bp` вместо `pop rbp`.'],
  ['x64-conv-shadow', 'x64-conv-align', 'leave'], 'пролог эпилог кадр')
V('leaf', 'своя процедура', ['своя процедура', 'процедура', 'функция'], 'договор о регистрах',
  code('# вход: AL — байт', '# выход: AH — старшая цифра, AL — младшая', 'hextochar:', '    ...', '    ret'),
  'Процедура, которая никого не вызывает (как `hextochar`), может обойтись без пролога и shadow space: она лишь возвращает RSP к значению на входе и сохраняет RBX, RBP, RDI, RSI, R12…R15. Параметры и результат — как у Windows или по своему договору (в лабе AL на входе, AX на выходе); договор пишут в комментарии над процедурой.',
  code('    mov     al, 0x5A            # параметр процедуры', '    call    hextochar           # AH = \'5\', AL = \'A\''),
  ['Регистр-параметр не загружен перед `call` — процедура берёт то, что осталось от прошлых команд.',
    'Процедура, которая сама вызывает API, обязана выровнять стек и выделить shadow space.'],
  ['call', 'ret', 'x64-err-al-unset'], 'процедура подпрограмма')

/* ── kernel32 ────────────────────────────────────────────── */

function slotName(i: number): string {
  const s = argSlot(i)
  return 'reg' in s ? s.reg.toUpperCase() : `[RSP+${s.stack}]`
}

/** Прототип по строкам параметров: в узком окне одна длинная строка не читается. */
function protoText(f: WinFunction): string {
  if (f.params.length <= 1) return f.proto
  const open = f.proto.indexOf('(')
  return `${f.proto.slice(0, open + 1)}\n    ${f.params.map((p) => `${p.type} ${p.name}`).join(',\n    ')})`
}

function K(name: string, short: string, desc: string, ex: string, errs: string[], see: string[], kw: string) {
  const f = WINAPI[name]
  if (!f) return
  const inn: DocIoRow[] = f.params.map((p, i) => [slotName(i), `${p.name} — ${p.note}`])
  const out: DocIoRow[] = []
  if (f.noreturn) out.push(['—', f.returns.note])
  else {
    if (f.returns.size) out.push([f.returns.size === 8 ? 'RAX' : 'EAX', f.returns.note])
    for (const p of f.params) if (p.role === 'outCount') out.push([`[${p.name}]`, p.note])
    out.push(['RCX RDX R8–R11', 'портятся вызовом'])
  }
  const l = name.toLowerCase()
  add({
    id: `x64-api-${l}`, sec: 'api', name, alias: [l, `kernel32.${l}`, `__imp_${l}`], short,
    syntax: protoText(f), desc, io: { in: inn, out }, ex, errs, see, kw: `kernel32 winapi функция ${kw}`,
  })
}

K('GetStdHandle', 'дескриптор консоли',
  'Возвращает дескриптор стандартного ввода (−10, STD_INPUT_HANDLE), вывода (−11, STD_OUTPUT_HANDLE) или ошибок (−12, STD_ERROR_HANDLE). Дескриптор сохраняют в переменную: RAX испортится следующим же вызовом. Параметров в стеке нет, но shadow space и выравнивание нужны, как перед любым `call`.',
  code(
    '    mov     rcx, -11            # STD_OUTPUT_HANDLE',
    '    call    GetStdHandle',
    '    mov     [rip+handle], rax   # сохранить дескриптор',
  ),
  ['`mov rcx, 11` без минуса — неверный номер потока: в RAX вернётся −1 (INVALID_HANDLE_VALUE).',
    'Дескриптор оставлен в RAX — после следующего вызова его нет.',
    'Вызов до `sub rsp, …` — без shadow space.'],
  ['x64-api-writefile', 'x64-api-readfile', 'x64-conv-shadow'], 'stdout stdin stderr консоль дескриптор')
K('WriteFile', 'вывод байтов',
  'Пишет байты буфера в файл или консоль; с консолью работает и тогда, когда вывод программы перенаправлен в файл. Вывод программы в трассе — это байты её `WriteFile` и `WriteConsoleA`. Число выведенных байт функция пишет в DWORD по адресу из R9.',
  WRITEFILE_CALL,
  ['Длина с нулевым байтом (`.equ meslen, .-message` после `.asciz`) — выводится лишний NUL.',
    'В R9 значение (`mov r9, [rip+written]`) вместо адреса — функция пишет счётчик по случайному адресу; нужен `lea`.',
    'Пятый параметр не в `qword ptr [rsp+32]` или не 0 — `lpOverlapped` получает мусор, и вызов может вернуть 0 или испортить память.',
    '`lpNumberOfBytesWritten` = 0 разрешён только вместе с ненулевым `lpOverlapped`.'],
  ['x64-api-getstdhandle', 'x64-api-writeconsolea', 'x64-conv-stack', 'x64-api-getlasterror'], 'вывод строки печать stdout')
K('ReadFile', 'ввод байтов',
  'Читает до `nNumberOfBytesToRead` байт в буфер и пишет число прочитанных в DWORD по адресу из R9. С консоли строка приходит вместе с `\\r\\n`, оба байта входят в счётчик; из файла или канала байты приходят как есть. Когда ввод кончился, функция возвращает TRUE и 0 прочитанных байт. В прогоне, где заданный ввод исчерпан, программа останавливается на этом вызове как ожидающая ввода.',
  code(
    '    mov     rcx, [rip+hin]              # дескриптор из GetStdHandle(-10)',
    '    lea     rdx, [rip+buf]',
    '    mov     r8, 64                      # размер буфера',
    '    lea     r9, [rip+nread]',
    '    mov     qword ptr [rsp+32], 0',
    '    call    ReadFile',
    '    mov     rcx, [rip+nread]            # сколько прочитано',
  ),
  ['Буфер меньше `nNumberOfBytesToRead` — лишние байты затрут соседние переменные.',
    'Прочитанное выводят длиной из счётчика (`mov r8, [rip+nread]`), а не размером буфера.',
    '`\\r\\n` в конце строки не убран — при переводе в число это два лишних символа.'],
  ['x64-api-getstdhandle', 'x64-api-readconsolea', 'gas-space'], 'ввод строки stdin чтение')
K('WriteConsoleA', 'вывод в консоль',
  'Пишет символы в консоль. Работает только с консолью: если вывод программы перенаправлен в файл или канал, на Windows функция возвращает 0 (ошибка 6, неверный дескриптор) — там нужен `WriteFile`. Пятый параметр `lpReserved` — 0.',
  code(
    '    mov     rcx, [rip+handle]',
    '    lea     rdx, [rip+message]',
    '    mov     r8, meslen',
    '    lea     r9, [rip+written]',
    '    mov     qword ptr [rsp+32], 0       # lpReserved',
    '    call    WriteConsoleA',
  ),
  ['Вывод, перенаправленный в файл (`prog.exe > out.txt`), — ничего не записано, EAX = 0.',
    'Кириллица из исходника в UTF-8 в консоли Windows с кодовой страницей 866 выглядит кракозябрами.'],
  ['x64-api-writefile', 'x64-api-getlasterror'], 'вывод консоль печать')
K('ReadConsoleA', 'ввод с консоли',
  'Читает строку с консоли до Enter; в буфер попадают символы и `\\r\\n`. Как и `WriteConsoleA`, работает только с консолью: с перенаправленным вводом на Windows возвращает 0. `pInputControl` — 0.',
  code(
    '    mov     rcx, [rip+hin]',
    '    lea     rdx, [rip+buf]',
    '    mov     r8, 64',
    '    lea     r9, [rip+nread]',
    '    mov     qword ptr [rsp+32], 0       # pInputControl',
    '    call    ReadConsoleA',
  ),
  ['Ввод из файла (`prog.exe < in.txt`) — вызов не удаётся; для файла `ReadFile`.'],
  ['x64-api-readfile', 'x64-api-writeconsolea'], 'ввод консоль клавиатура')
K('ExitProcess', 'завершить программу',
  'Завершает процесс с кодом из ECX; управление не возвращается. Выравнивание и shadow space нужны и здесь. Программа может закончиться и `ret` из `main` с кодом в EAX — Windows завершит процесс так же.',
  code('    xor     ecx, ecx            # код 0', '    call    ExitProcess'),
  ['Код положен в EAX перед `call ExitProcess` — код берётся из ECX.', 'Команды после `call ExitProcess` не выполняются.'],
  ['ret', 'x64-conv-ret'], 'выход завершение код возврата exit')
K('GetLastError', 'код последней ошибки',
  'Возвращает в EAX код ошибки последней неудачной функции этого потока. Звать сразу после вызова, вернувшего 0: следующий вызов может код перезаписать. Частые коды: 6 — неверный дескриптор, 87 — неверный параметр, 998 — неверный адрес буфера.',
  code(
    '    call    WriteFile',
    '    test    eax, eax            # 0 — ошибка',
    '    jnz     ok',
    '    call    GetLastError        # EAX = код ошибки',
    'ok:',
  ),
  ['Между неудачным вызовом и `GetLastError` стоит другой вызов API — код уже не тот.'],
  ['x64-conv-ret', 'x64-api-writefile'], 'ошибка код')

/* ── сборка ──────────────────────────────────────────────── */

function B(key: string, name: string, alias: string[], short: string, syntax: string, desc: string, errs: string[], see: string[], kw: string) {
  add({ id: `x64-build-${key}`, sec: 'build', name, alias, short, syntax, desc, errs, see, kw: `сборка ${kw}` })
}

B('as', 'as', ['as', 'x86_64-w64-mingw32-as', '-a=', 'ассемблер', 'листинг'], 'ассемблирование и листинг',
  code(
    'as -a=prog.lst prog.s -o prog.obj',
    '',
    '# листинг: номер строки, смещение, байты, текст',
    '  14 0000 55           push    rbp',
    '  16 0004 4883EC30     sub     rsp, 48',
    '  19 000f E8000000     call    GetStdHandle',
    '  19      00',
  ),
  '`as` переводит исходник в объектный файл COFF x64. `-a=prog.lst` пишет листинг: номер строки исходника, смещение в секции, байты команды и текст, в конце — таблицу символов. Адреса внешних имён (`GetStdHandle`) и RIP-смещения в листинге нулевые: их вычисляет `ld`. Имена файлов и `-a=` подставляет сборка; в параметрах сборки добавляются только свои флаги (`-g`, `--warn`).',
  ['Ошибки `as` приходят строкой `prog.s:12: Error: …` — число после имени файла это номер строки исходника.'],
  ['x64-build-ld', 'x64-build-nosuch'], 'ассемблер листинг')
B('ld', 'ld', ['ld', 'x86_64-w64-mingw32-ld', '-lkernel32', '-l', 'компоновщик', 'линковщик'], 'компоновка .exe',
  'ld -o prog.exe prog.obj -L <каталог библиотек> -lkernel32',
  '`ld` собирает `prog.exe` (PE32+, база 0x140000000): раскладывает секции, разрешает внешние имена по библиотеке импорта `libkernel32.a` (`-L` — где её искать, `-lkernel32` — какую взять) и для каждой функции ставит переходник `jmp qword ptr [rip+__imp_WriteFile]` и ячейку в таблице импорта. Без `-e` точка входа — начало `.text` (с предупреждением про `mainCRTStartup`).',
  ['Ошибки `ld` указывают место как `prog.obj:prog.s:(.text+0x10)` — смещение в секции ищется в листинге.'],
  ['x64-build-as', 'x64-build-entry', 'x64-build-undef'], 'компоновщик kernel32')
B('nosuch', 'Error: no such instruction', ['no such instruction', 'invalid character'], 'as: незнакомая команда',
  "prog.s:12: Error: no such instruction: `movv rax,1'",
  '`as` не узнал первое слово команды. Причины: опечатка в мнемонике; комментарий через `;` — у GAS `;` разделяет команды, и текст после него читается как новая команда (кириллица даёт «invalid character … in mnemonic»); директива без точки (`quad 0`); запись TASM (`db 5`, `end start`).',
  [], ['gas-comment', 'x64-build-pseudo'], 'ошибка as')
B('ambig', 'Error: ambiguous operand size', ['ambiguous operand size'], 'as: размер не указан',
  "prog.s:29: Error: ambiguous operand size for `mov'",
  'В команде нет регистра, из которого берётся размер: число в память, `inc` или `neg` ячейки, источник `movzx`. Нужен `qword ptr`, `dword ptr`, `word ptr` или `byte ptr`.',
  [], ['x64-addr-ptr'], 'ошибка as размер')
B('mismatch', 'Error: operand size / type mismatch', ['operand size mismatch', 'operand type mismatch', "can't encode register"], 'as: операнды не подходят',
  "prog.s:14: Error: operand size mismatch for `push'\nprog.s:15: Error: operand type mismatch for `lea'",
  'Операнды несовместимы с командой: разные размеры (`mov eax, rbx`), 32-битный `push eax`, `movzx rax, eax`, `sete eax`, число там, где нужен адрес (`lea rax, 5`), счётчик сдвига не в CL. «can\'t encode register \'ah\'» — AH рядом с SIL, DIL, R8B и подобными.',
  [], ['push', 'movzx', 'x64-reg-parts'], 'ошибка as размер тип')
B('junk', 'Error: junk … after expression', ['junk', 'junk at end of line', 'after expression', 'bad expression'], 'as: лишнее в операнде',
  "prog.s:13: Error: junk `2' after expression",
  'После операнда остались лишние символы: пропущена запятая или закрывающая скобка (`[rsp+32`), пробел внутри числа, комментарий без `#`.',
  [], ['gas-comment'], 'ошибка as')
B('pseudo', 'Error: unknown pseudo-op', ['unknown pseudo-op'], 'as: незнакомая директива',
  "prog.s:8: Error: unknown pseudo-op: `.model'",
  'Директива с точкой, которой нет в GAS: опечатка (`.quadd`) или директива TASM (`.model`, `.stack`, `.code`). У GAS секции — `.text`, `.data`, `.bss`, стек отдельно не объявляется.',
  [], ['gas-text', 'gas-data', 'x64-build-nosuch'], 'ошибка as директива')
B('undef', 'undefined reference to', ['undefined reference', 'undefined reference to'], 'ld: имя не найдено',
  "ld: prog.obj:prog.s:(.text+0x10): undefined reference to `WriteFil'",
  '`ld` не нашёл определения имени: опечатка или регистр букв в имени функции (`writefile` вместо `WriteFile`), функция не из kernel32, метка не объявлена. Смещение `.text+0x10` ищется в листинге — это строка с обращением.',
  ['Декорированные имена 32-битных функций (`_WriteFile@20`) в x64 не нужны: имя пишется как есть.'],
  ['x64-build-ld', 'gas-label'], 'ошибка ld компоновка')
B('entry', 'cannot find entry symbol mainCRTStartup', ['cannot find entry symbol', 'maincrtstartup', 'entry symbol'], 'ld: предупреждение о точке входа',
  'ld: warning: cannot find entry symbol mainCRTStartup; defaulting to 0000000140001000',
  'Предупреждение, а не ошибка: `.exe` собран. `ld` по умолчанию ищет точку входа `mainCRTStartup` (её даёт библиотека C, которой здесь нет) и берёт начало секции `.text`. Поэтому первой командой после `.text` должна идти `main`. Задать точку входа явно — флаг `-e main` в параметрах `ld`.',
  [], ['gas-globl', 'x64-build-ld'], 'точка входа предупреждение ld')
B('reloc', 'relocation truncated to fit', ['relocation truncated', 'relocation truncated to fit'], 'ld: адрес не помещается',
  "ld: prog.obj:prog.s:(.text+0x1b): relocation truncated to fit: … against `.data'",
  'Команда требует 32-битного абсолютного адреса, а образ лежит выше 4 ГБ (0x140000000). Почти всегда это обращение к переменной без `rip`: `mov rax, [message]`, `mov rax, message`, `mov eax, offset message`. Исправление — `[rip+метка]` для значения и `lea` для адреса.',
  [], ['x64-addr-rip', 'x64-addr-abs'], 'ошибка ld адрес')

/* ── типовые ошибки лабораторных ─────────────────────────── */

function P(key: string, name: string, alias: string[], short: string, syntax: string, desc: string, ex: string, see: string[], kw: string) {
  add({ id: `x64-err-${key}`, sec: 'pitfall', name, alias, short, syntax, desc, ex, see, kw: `ошибка лаба ${kw}` })
}

P('pop-bp', 'pop bp вместо pop rbp', ['pop bp'], 'стек съезжает на 6 байт',
  'было:   pop     bp\nнадо:   pop     rbp',
  '`push rbp` кладёт 8 байт, а `pop bp` снимает 2. Команда законная, `as` молчит. После неё RSP на 6 больше, чем был до `push`, в RBP заменены только младшие 16 бит. `ret` читает адрес возврата со сдвигом на 6 байт, получает мусор, и программа падает прямо на `ret`. В трассе: после `pop bp` последняя hex-цифра RSP — 2 (…F72 вместо …F78), у RBP странные младшие 4 цифры.',
  code('    add     rsp, 48', '    xor     eax, eax', '    pop     rbp', '    ret'),
  ['pop', 'x64-conv-frame', 'ret'], 'стек pop')
P('ah-al', 'add al вместо add ah', ['add al', 'add ah'], 'прибавка не в тот байт',
  "было:   over92: add al, 'A'\n                sub ah, 10\nнадо:   over92: add ah, 'A'\n                sub ah, 10",
  "В `hextochar` старшая цифра живёт в AH, младшая — в AL. `add al, 'A'` в ветке старшей цифры портит уже готовую младшую, а AH получает только `sub ah, 10`. На байте 0x5A ошибка не видна: старшая цифра 5 идёт веткой `add ah, '0'`. Проверять нужно байтом со старшей цифрой A–F: для 0xA5 выйдет AH = 0x00 и AL = 'v' (0x76) вместо 'A' и '5'.",
  code('over92:', "    add     ah, 'A'", '    sub     ah, 10'),
  ['add', 'x64-reg-parts'], 'регистр байт ah al')
P('rsp31', '[rsp+31] вместо qword ptr [rsp+32]', ['[rsp+31]', 'mov [rsp+31], r9'], 'пятый параметр мимо ячейки',
  'было:   mov     [rsp+31], r9\nнадо:   mov     qword ptr [rsp+32], 0',
  'Пятый параметр `WriteFile` (`lpOverlapped`) — 8 байт по `[rsp+32]`, для консоли он 0. Запись R9 с `[rsp+31]` ложится со сдвигом на байт: младший байт R9 уходит в shadow space, а в `lpOverlapped` оказываются остальные 7 байт адреса счётчика и один чужой. Функция получает ненулевой `lpOverlapped` и читает его как структуру OVERLAPPED — вызов может вернуть 0 или испортить память. В трассе перед `call`: 8 байт по RSP+32 не нули.',
  code('    lea     r9, [rip+written]           # 4-й параметр — в регистре', '    mov     qword ptr [rsp+32], 0       # 5-й — в стеке', '    call    WriteFile'),
  ['x64-conv-stack', 'x64-addr-ptr', 'x64-api-writefile'], 'пятый параметр стек')
P('noshadow', 'нет shadow space перед GetStdHandle', ['нет shadow space'], 'вызов без 32 байт над RSP',
  'было:   push rbp · mov rbp, rsp · mov rcx, -11 · call GetStdHandle · … sub rsp, 48\nнадо:   push rbp · mov rbp, rsp · sub rsp, 48 · mov rcx, -11 · call GetStdHandle',
  'Место под shadow space резервируется в прологе, до первого `call`. Без него [RSP]…[RSP+31] в момент вызова — сохранённый RBP, адрес возврата из `main` и то, что выше, и функция вправе туда писать. Ошибка может не проявиться (функция не тронула эти байты) и проявиться на другой машине — падением на `ret` из `main` или испорченным RBP. В трассе перед `call`: RSP равен RBP, а должен быть на 48 меньше.',
  code('main:', '    push    rbp', '    mov     rbp, rsp', '    sub     rsp, 48', '    mov     rcx, -11', '    call    GetStdHandle'),
  ['x64-conv-shadow', 'x64-conv-frame'], 'shadow space')
P('sub56', 'sub rsp, 56 вместо 48', ['sub rsp, 56'], 'RSP не кратен 16 перед call',
  'было:   sub     rsp, 56\nнадо:   sub     rsp, 48',
  'На входе в `main` RSP ≡ 8 (mod 16), `push rbp` делает его кратным 16, и `sub` должен кратность сохранить: 32 (shadow space) + 8 (пятый параметр) = 40, вверх до кратного 16 — 48. С 56 RSP перед `call` ≡ 8 — нарушение соглашения. Функции Windows с выровненными SSE-командами падают внутри вызова, остальные работают — ошибка плавающая. В трассе: последняя hex-цифра RSP на строке `call` — 8, а не 0. `add rsp` в эпилоге — то же число, что `sub`.',
  code('    sub     rsp, 48             # 32 + 8, кратно 16', '    ...', '    add     rsp, 48'),
  ['x64-conv-align', 'sub'], 'выравнивание стек')
P('meslen', '.equ meslen, .-message с нулём', ['.-message', 'meslen', 'длина строки'], 'длина строки с нулевым байтом',
  'было:   .equ    meslen, .-message\nнадо:   .equ    meslen, .-message-1',
  '`.asciz` дописывает байт 0, и `.-message` сразу после строки считает и его: 11 вместо 10 для "Hello GAS\\n". `WriteFile` выводит этот NUL — в выводе лишний невидимый символ, в файле лишний байт. В трассе: R8 = 0xB перед `call WriteFile`, в `written` после вызова — 11.',
  code('message:    .asciz  "Hello GAS\\n"', '    .equ    meslen, .-message-1         # длина без нулевого байта'),
  ['gas-asciz', 'gas-dot', 'x64-api-writefile'], 'длина строки нуль')
P('al-unset', 'AL не задан перед hextochar', ['al не задан', 'hextochar'], 'параметр процедуры не загружен',
  'было:   call    hextochar\nнадо:   mov     al, 0x5A\n        call    hextochar',
  '`hextochar` берёт байт из AL. Без `mov al, 0x5A` в AL остаётся младший байт RAX от прошлой команды — дескриптора, который вернул `GetStdHandle`. Процедура честно переводит этот байт, программа не падает, но результат не тот. В трассе: на шаге `call hextochar` AL не равен 0x5A.',
  code('    mov     al, 0x5A            # байт для преобразования', "    call    hextochar           # AH = '5', AL = 'A'"),
  ['x64-conv-leaf', 'rax'], 'параметр процедура регистр')

/* ── AT&T ↔ Intel ────────────────────────────────────────── */

add({
  id: 'x64-att', sec: 'att', name: 'AT&T ↔ Intel', alias: ['at&t', 'att', 'intel', '%', '$'], short: 'две записи одних команд',
  syntax: code(
    'Intel (.intel_syntax noprefix)      AT&T (по умолчанию)',
    'mov     rax, rbx                    movq    %rbx, %rax',
    'mov     rcx, -11                    movq    $-11, %rcx',
    'mov     r8, meslen                  movq    $meslen, %r8',
    'mov     rax, [rip+handle]           movq    handle(%rip), %rax',
    'lea     rdx, [rip+message]          leaq    message(%rip), %rdx',
    'mov     qword ptr [rsp+32], 0       movq    $0, 32(%rsp)',
    'mov     rax, [rbx+rsi*8+16]         movq    16(%rbx,%rsi,8), %rax',
    'movzx   eax, byte ptr [rsi]         movzbl  (%rsi), %eax',
    'movsxd  rax, ecx                    movslq  %ecx, %rax',
    'cqo · cdqe                          cqto · cltq',
    'push    rbp                         pushq   %rbp',
    'call    rax                         call    *%rax',
    'jmp     qword ptr [rip+tab]         jmp     *tab(%rip)',
    'shl     ax, 4                       shlw    $4, %ax',
  ),
  desc: 'Порядок операндов обратный: в AT&T приёмник последний. Регистры пишутся с `%`, непосредственные числа с `$` — без `$` число или имя означает память. Размер — суффиксом команды: `b` 1, `w` 2, `l` 4, `q` 8 байт — вместо `byte/word/dword/qword ptr`. Адрес — `смещение(база,индекс,масштаб)` вместо `[база+индекс*масштаб+смещение]`. Косвенные переходы и вызовы — со звёздочкой. Комментарий `#` и разделитель `;` одинаковы. В одном файле синтаксис переключают `.intel_syntax noprefix` и `.att_syntax`.',
  errs: ['`movq handle, %rax` без `(%rip)` — абсолютный 32-битный адрес, `ld` откажет.',
    '`mov $5, 32(%rsp)` без суффикса: `as` предупреждает «no instruction mnemonic suffix given and no register operands» и берёт размер по умолчанию — не обязательно 8 байт.',
    'Забытый `$`: `movq 5, %rax` читает 8 байт по адресу 5 и падает.'],
  see: ['gas-syntax', 'x64-addr-ptr', 'x64-addr-sib'], kw: 'синтаксис перевод суффикс процент доллар',
})

export const DOC_ENTRIES_64: readonly DocEntry[] = list
