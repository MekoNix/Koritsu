    .intel_syntax noprefix
    .globl  main
    .data
hout:   .quad   0
nwr:    .quad   0
msg:    .ascii  "after int3\n"
    .equ    mlen, .-msg
    .text
main:
    push    rbp
    mov     rbp, rsp
    sub     rsp, 48
    mov     rcx, -11
    call    GetStdHandle
    mov     [rip+hout], rax
    int3
    mov     rcx, [rip+hout]
    lea     rdx, [rip+msg]
    mov     r8, mlen
    lea     r9, [rip+nwr]
    mov     qword ptr [rsp+32], 0
    call    WriteFile
    mov     eax, 3
    add     rsp, 48
    pop     rbp
    ret
