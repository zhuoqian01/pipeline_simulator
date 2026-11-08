# Nested loops: sum of an 8 x 8 matrix, loops tested at the bottom (do-while style).
#   for (i = 0; i < 8; i++) for (j = 0; j < 8; j++) sum += M[i][j];
# mapping: M -> a0, i -> t0, j -> t1, sum -> s0, N -> t5.  Result stored at M[64]: 2080
.reg  a0 = 0x3000
.word 0x3000 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60 61 62 63 64
        addi s0, zero, 0
        addi t0, zero, 0
        addi t5, zero, 8
outer:  addi t1, zero, 0
inner:  slli t2, t0, 3          # i * 8
        add  t2, t2, t1         # i * 8 + j
        slli t2, t2, 2          # byte offset
        add  t3, a0, t2
        lw   t4, 0(t3)          # M[i][j]
        add  s0, s0, t4
        addi t1, t1, 1
        bne  t1, t5, inner      # inner loop branch: taken 7 times, then not taken
        addi t0, t0, 1
        bne  t0, t5, outer
        sw   s0, 256(a0)
