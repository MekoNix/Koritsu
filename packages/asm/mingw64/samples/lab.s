    .intel_syntax noprefix      #включаем режим интеловской нотации без префикса
    .globl  main                #определяем имя точки входа в программу
    .data
    .p2align 4
handle:     .quad   0           #дескриптор консоли (8 байт достаточно)
written:    .quad   0           #сюда WriteFile положит число записанных байт
num1:       .float  -1.4
num2:       .double 101.2
arra:       .space  64
message:    .asciz  "Hello GAS\n"       #текст выводимого сообщения
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
