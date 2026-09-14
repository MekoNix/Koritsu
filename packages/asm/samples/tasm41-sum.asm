; sum.asm ? читает цифру N и выводит сумму первых N элементов массива
.model small
.stack 100h
.data
arr     db 3, 7, 12, 5, 9
prompt  db 'N = $'
res     db 13, 10, 'Sum = $'
.code
start:  mov  ax, @data
        mov  ds, ax
        mov  ah, 09h
        mov  dx, offset prompt
        int  21h
        mov  ah, 01h        ; ввод символа -> AL
        int  21h
        sub  al, '0'
        xor  ah, ah
        mov  cx, ax         ; CX = N
        xor  bx, bx         ; BX = сумма
        mov  si, offset arr
next:   mov  al, [si]
        add  bl, al
        inc  si
        loop next
        mov  ah, 09h
        mov  dx, offset res
        int  21h
        mov  ax, bx
        mov  dl, 10
        div  dl             ; AL = десятки, AH = единицы
        mov  dx, ax
        add  dx, 3030h
        mov  ah, 02h
        int  21h            ; печать DL (десятки)
        mov  dl, dh
        int  21h            ; печать единиц
        mov  ax, 4C00h
        int  21h
end start
