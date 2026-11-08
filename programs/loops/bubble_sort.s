# Bubble sort of 12 numbers (data-dependent branches).
#   for (i = 0; i < n-1; i++) for (j = 0; j < n-1-i; j++) if (A[j] > A[j+1]) swap
# mapping: A -> a0, n -> a1, i -> s0, j -> s1.  Sorted result: [8, 8, 16, 29, 55, 71, 73, 74, 75, 75, 81, 81]
.reg  a0 = 0x4000
.reg  a1 = 12
.word 0x4000 71 55 8 73 16 29 81 81 75 8 74 75
        addi s0, zero, 0
        addi s3, a1, -1           # n - 1
outer:  bge  s0, s3, done
        addi s1, zero, 0          # j = 0
        sub  s2, s3, s0           # n - 1 - i
inner:  bge  s1, s2, next_i
        slli t0, s1, 2
        add  t0, a0, t0           # address of A[j]
        lw   t1, 0(t0)            # A[j]
        lw   t2, 4(t0)            # A[j+1]
        bge  t2, t1, noswap       # A[j+1] >= A[j]: already in order
        sw   t2, 0(t0)
        sw   t1, 4(t0)
noswap: addi s1, s1, 1
        beq  zero, zero, inner
next_i: addi s0, s0, 1
        beq  zero, zero, outer
done:   addi a2, zero, 1
