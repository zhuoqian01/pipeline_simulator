# Topic 3, timing diagram example: six independent loads.
# Expected (any model): CC needed = 10, penalty = 0 CC, CPI = (10-4)/6 = 1
I1: lw x2, 0(x1)
I2: lw x3, 4(x1)
I3: lw x4, 8(x1)
I4: lw x5, 12(x1)
I5: lw x6, 16(x1)
I6: lw x7, 20(x1)
