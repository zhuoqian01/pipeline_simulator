# Results summary (pipeline_evaluator_v2)

Random programs use seed 2026. CPI = (CC needed - 4) / IC. T_clk: single-cycle 2.0 ns, pipeline 0.6 ns.

## Graph 1 - lecture examples (all match the class notes)

| Program | Model | CC needed | Penalty (CC) | CPI |
|---|---|---|---|---|
| ex3_lw_sub_addi_sw_ori | Pipeline without forwarding (stall/nop) | 13 | 4 | 1.80 |
| ex3_lw_sub_addi_sw_ori | Rearrange without forwarding | 9 | 0 | 1.00 |
| ex3_lw_sub_addi_sw_ori | Pipeline with forwarding (A/B/C) | 10 | 1 | 1.20 |
| ex2_add_sub_and_or | Pipeline without forwarding (stall/nop) | 10 | 2 | 1.50 |
| ex2_add_sub_and_or | Pipeline with forwarding (A/B/C) | 8 | 0 | 1.00 |
| ex4_add_lw_sw | Pipeline without forwarding (stall/nop) | 11 | 4 | 2.33 |
| ex4_add_lw_sw | Pipeline with forwarding (A/B/C) | 7 | 0 | 1.00 |

## Graph 2 - CPI vs dependency probability (2000 programs of 20 instructions per point)

| dep. prob. | Pipeline without forwarding (stall/nop) | Rearrange without forwarding | Pipeline with forwarding (A/B/C) | Forwarding + rearrange |
|---|---|---|---|---|
| 0.0 | 1.000 | 1.000 | 1.000 | 1.000 |
| 0.5 | 1.512 | 1.272 | 1.061 | 1.015 |
| 1.0 | 1.931 | 1.840 | 1.122 | 1.095 |

## Graph 3 - penalty breakdown (CC per instruction; CPI = 1 + sum)

| Group | Model | ALU-use | Load-use | Branch | CPI |
|---|---|---|---|---|---|
| random | Pipeline without forwarding (stall/nop) | 0.353 | 0.168 | 0.000 | 1.521 |
| loops | Pipeline without forwarding (stall/nop) | 0.748 | 0.221 | 0.528 | 2.497 |
| random | Rearrange without forwarding | 0.185 | 0.092 | 0.000 | 1.277 |
| loops | Rearrange without forwarding | 0.597 | 0.221 | 0.528 | 2.346 |
| random | Pipeline with forwarding (A/B/C) | 0.000 | 0.058 | 0.000 | 1.058 |
| loops | Pipeline with forwarding (A/B/C) | 0.000 | 0.110 | 0.528 | 1.639 |
| random | Forwarding + rearrange | 0.000 | 0.014 | 0.000 | 1.014 |
| loops | Forwarding + rearrange | 0.000 | 0.055 | 0.528 | 1.583 |

## Graph 4 - speedup vs single-cycle processor (x)

| Workload | Pipeline without forwarding (stall/nop) | Rearrange without forwarding | Pipeline with forwarding (A/B/C) | Forwarding + rearrange | Forwarding + rearrange + 2-bit predictor |
|---|---|---|---|---|---|
| Random (dep. 0.5) | 2.20 | 2.62 | 3.15 | 3.29 | 3.29 |
| for loop (sum i) | 1.69 | 1.69 | 1.72 | 1.72 | 2.94 |
| array sum | 1.38 | 1.47 | 1.96 | 2.13 | 3.20 |
| while loop | 1.34 | 1.40 | 2.07 | 2.07 | 2.84 |
| nested loop (8x8) | 1.23 | 1.41 | 2.41 | 2.63 | 3.18 |
| bubble sort | 1.41 | 1.41 | 1.83 | 1.83 | 2.73 |

## Graph 5 - branch prediction, CPI (wrong guesses / stalls) with forwarding

| Program | IC | Branches | Stall (insert nop) | Predict NOT taken | Predict taken | 1-bit dynamic | 2-bit dynamic |
|---|---|---|---|---|---|---|---|
| for_sum | 45 | 21 | 1.93 (21) | 1.49 (11) | 1.44 (10) | 1.09 (2) | 1.13 (3) |
| array_sum | 145 | 41 | 1.70 (41) | 1.43 (21) | 1.41 (20) | 1.17 (2) | 1.18 (3) |
| while_loop | 127 | 31 | 1.61 (31) | 1.38 (16) | 1.36 (15) | 1.16 (2) | 1.17 (3) |
| nested_loop | 540 | 72 | 1.39 (72) | 1.35 (63) | 1.15 (9) | 1.19 (18) | 1.17 (13) |
| bubble_sort | 646 | 232 | 1.82 (232) | 1.51 (131) | 1.41 (101) | 1.25 (47) | 1.22 (38) |

## Graph 6 - convergence (mean penalty ± 95% CI, 10-instruction programs)

| Model | 100 | 1000 | 50000 |
|---|---|---|---|
| Pipeline without forwarding (stall/nop) | 5.110 ± 0.489 | 5.103 ± 0.139 | 5.029 ± 0.020 |
| Rearrange without forwarding | 2.950 ± 0.490 | 2.985 ± 0.144 | 2.981 ± 0.020 |
| Pipeline with forwarding (A/B/C) | 0.610 ± 0.155 | 0.618 ± 0.046 | 0.601 ± 0.007 |
| Forwarding + rearrange | 0.200 ± 0.100 | 0.180 ± 0.028 | 0.189 ± 0.004 |

