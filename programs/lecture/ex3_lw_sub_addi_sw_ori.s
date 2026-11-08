# Topic 3, data hazard Ex.2 (RAW I1->I2 on x1, I3->I4 on x6).
# Expected: no forwarding: CC = 13, penalty = 4 CC, CPI = 1.8
#           rearranged (lw, addi, ori, sub, sw), no forwarding: CC = 9, penalty = 0, CPI = 1
#           forwarding:    CC = 10, penalty = 1 CC (load-use), CPI = 1.2
I1: lw   x1, 0(x2)
I2: sub  x4, x1, x5
I3: addi x6, x3, 10
I4: sw   x6, 4(x2)
I5: ori  x7, x8, 1
