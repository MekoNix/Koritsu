    .intel_syntax noprefix
    .globl  main
    .data
    .p2align 4
hin:    .quad   0
hout:   .quad   0
nread:  .quad   0
nwr:    .quad   0
prompt: .ascii  "Enter: "
    .equ    plen, .-prompt
buf:    .space  64
    .text
main:
    push    rbp
    mov     rbp, rsp
    sub     rsp, 48
    mov     rcx, -10            #STD_INPUT_HANDLE
    call    GetStdHandle
    mov     [rip+hin], rax
    mov     rcx, -11            #STD_OUTPUT_HANDLE
    call    GetStdHandle
    mov     [rip+hout], rax
    mov     rcx, [rip+hout]
    lea     rdx, [rip+prompt]
    mov     r8, plen
    lea     r9, [rip+nwr]
    mov     qword ptr [rsp+32], 0
    call    WriteFile
    mov     rcx, [rip+hin]
    lea     rdx, [rip+buf]
    mov     r8, 64
    lea     r9, [rip+nread]
    mov     qword ptr [rsp+32], 0
    call    ReadFile
    #короткий цикл: строчные латинские в заглавные
    lea     rsi, [rip+buf]
    mov     rcx, [rip+nread]
    test    rcx, rcx
    jz      done
up:
    mov     al, [rsi]
    cmp     al, 'a'
    jb      skip
    cmp     al, 'z'
    ja      skip
    sub     al, 32
    mov     [rsi], al
skip:
    inc     rsi
    loop    up
done:
    mov     rcx, [rip+hout]
    lea     rdx, [rip+buf]
    mov     r8, [rip+nread]
    lea     r9, [rip+nwr]
    mov     qword ptr [rsp+32], 0
    call    WriteFile
    mov     rax, [rip+nread]
    add     rsp, 48
    pop     rbp
    ret
