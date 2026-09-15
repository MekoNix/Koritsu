.model small
.stack 100h
print macro msg
        mov  ah, 09h
        mov  dx, offset msg
        int  21h
        endm
.data
buf     db 20 dup(0)
long    db 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
hello   db 'Hello, world from TASM listing test$'
w       dw 1234h, 5678h

.code
start:  mov  ax, @data
        mov  ds, ax
        print hello

        mov  cx, 3
again:  loop again
        mov  ax, 4C00h
        int  21h
end start
