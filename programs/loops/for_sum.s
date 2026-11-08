# Topic 2: for (i = 0; i < 10; i++) { a = a + i; }      mapping: a -> s0, i -> t0
# Result: s0 = 45
        addi s0, zero, 0
        addi t0, zero, 0
        addi t1, zero, 10
loop:   bge  t0, t1, exit
        add  s0, s0, t0
        addi t0, t0, 1
        beq  zero, zero, loop
exit:   addi s1, s0, 0
