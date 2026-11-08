# Topic 3, data hazard Ex.1 (RAW I1->I2, I1->I3, I1->I4; WAW I3->I4).
# Expected: no forwarding: CC = 10, penalty = 2 CC, CPI = 1.5
#           forwarding:    CC = 8,  penalty = 0 CC, CPI = 1   (x1 via path B to I2, path A to I3)
I1: add x1, x2, x3
I2: sub x4, x1, x5
I3: and x6, x1, x7
I4: or  x6, x1, x8
