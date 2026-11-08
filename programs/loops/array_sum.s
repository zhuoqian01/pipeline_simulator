# Topic 2 style: sum = 0; for (i = 0; i < 20; i++) sum = sum + A[i];
# mapping: A -> a0 (base address), i -> t0, sum -> s0.  Result stored at A[20]: 698
.reg  a0 = 0x1000
.word 0x1000 42 20 51 84 7 10 69 13 47 75 8 65 28 5 12 56 54 9 31 12
        addi s0, zero, 0
        addi t0, zero, 0
        addi t1, zero, 20
loop:   bge  t0, t1, exit
        slli t2, t0, 2          # 4 * i
        add  t3, a0, t2         # base + offset
        lw   t4, 0(t3)          # A[i]
        add  s0, s0, t4
        addi t0, t0, 1
        beq  zero, zero, loop
exit:   sw   s0, 80(a0)
