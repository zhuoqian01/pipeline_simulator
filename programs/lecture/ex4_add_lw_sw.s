# Topic 3, data hazard Ex.3 (RAW I1->I2, I1->I3 on x1, I2->I3 on x4).
# Expected: no forwarding: CC = 11, penalty = 4 CC, CPI = (11-4)/3 = 2.33
#           forwarding:    CC = 7,  penalty = 0 CC, CPI = 1   (paths B, A and C)
I1: add x1, x2, x3
I2: lw  x4, 0(x1)
I3: sw  x4, 12(x1)
