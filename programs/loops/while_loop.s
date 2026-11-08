# Topic 2: while (A[i] == a) { a = 2 * a - A[i]; i++; }
# mapping: A -> s3 (base address), a -> s0, i -> s1.  A has fifteen 5s then a 7, so i ends at 15.
.reg  s3 = 0x2000
.word 0x2000 5 5 5 5 5 5 5 5 5 5 5 5 5 5 5 7
        addi s0, zero, 5
        addi s1, zero, 0
loop:   slli t0, s1, 2          # 4 * i
        add  t1, s3, t0         # address of A[i]
        lw   t2, 0(t1)          # A[i]
        bne  t2, s0, exit
        slli t3, s0, 1          # 2 * a
        sub  s0, t3, t2         # a = 2a - A[i]
        addi s1, s1, 1          # i++
        beq  zero, zero, loop
exit:   addi s2, s1, 0
