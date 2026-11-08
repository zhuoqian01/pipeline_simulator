# Pipeline Simulator v2 (5-stage RISC-V: IM  Reg  ALU  DM  Reg)

Version 2 of `pipeline_evaluator.py`, rewritten to follow the CS 5375 class notes
(Topics 1-3). Python 3 only, plus `matplotlib` for the graphs (`pip install matplotlib`).

## How to run

```
python3 pipeline_evaluator_v2.py                  # control panel (menu), like v1
python3 pipeline_evaluator_v2.py --rounds 10000   # random evaluation, no menu
python3 pipeline_evaluator_v2.py --lecture        # lecture examples + timing diagrams
python3 pipeline_evaluator_v2.py --loops          # branch prediction on Topic 2 loops
python3 pipeline_evaluator_v2.py --file programs/loops/for_sum.s --branch 2bit
python3 -m unittest -v test_pipeline_v2           # 23 tests, all should say "ok"
python3 run_experiments_v2.py                     # all 6 graphs (~80 s; --quick for ~12 s)
```

`--style stall` draws timing diagrams the hardware-interlock way (`IM ** ** Reg ...`).
The default `nop` style draws stalls as nop rows, like "Solution 1: insert nop" in the notes.

## Files

| File / folder | What it is |
|---|---|
| `pipeline_evaluator_v2.py` | the simulator (all models, parser, predictors, diagrams, control panel) |
| `test_pipeline_v2.py` | tests: every lecture example + hazard, forwarding, rearranging and branch rules |
| `run_experiments_v2.py` | produces graphs 1-6, CSV data and `results/summary.md` |
| `programs/lecture/*.s` | the Topic 3 timing-diagram examples (expected numbers in each file's comments) |
| `programs/loops/*.s` | Topic 2 style programs: for loop, array sum, while loop, nested loop, bubble sort |
| `figures/` | graphs: `.png` for slides/video, `.pdf` for the report |
| `results/` | raw numbers (`.csv`) and `summary.md` with every table |

## Where each part is (team roles)

| Part | Section in `pipeline_evaluator_v2.py` |
|---|---|
| RISC-V program input and generator | 1-2: `InstructionSetsParser` (`parse`, `generate_random_program`) |
| Real execution (values, branch outcomes) | 3: `execute()` |
| Branch hazards and predictors | 4: `BranchPredictor` (stall, not taken, taken, 1-bit, 2-bit) |
| Cycle-accurate pipeline + forwarding A/B/C | 5: `time_pipeline()` |
| Safe rearranging | 6: `rearrange()` |
| The processor models | 7: `SimpleMicroProcessor`, `PipelineProcessorWithoutForwarding`, `ReorderingWithoutForwarding`, `PipelineProcessorWithForwarding`, `ForwardingWithReordering` |
| Timing diagrams | 8: `timing_diagram()` |
| Random evaluation report | 9: `EvaluationEngine` |

## Rules used (from the notes)

- Register file: write in the first half of the cycle, read in the second half.
- CPI = (CC needed - 4) / IC. Penalty = stall CC. CC needed = IC + 4 + penalty.
- **No forwarding**: a dependent instruction reads in Reg in the same cycle the producer
  writes (its final Reg): 2 CC at distance 1, 1 CC at distance 2 (ADD and LW alike).
- **Forwarding**: path B (ALU -> ALU, next instruction), path A (DM stage -> ALU, two
  instructions later or a load after its 1 CC load-use stall), path C (-> DM, e.g.
  `lw x4` then `sw x4`: no stall).
- **Rearranging**: only inside a basic block (never across a branch or label), never
  breaks a RAW, WAR or WAW dependency, keeps memory order around stores, and is never
  slower than the original. Every rearranged program is executed and checked.
- **Branches** are decided after the ALU: 2 CC penalty for stall / wrong prediction.
  2-bit predictor transitions exactly as the state diagram in the notes. Dynamic
  predictors start at "predict not taken".
- **Execution time** = IC x CPI x T_clk with T_clk = 2 ns (single-cycle, CPI = 1) and
  0.6 ns (pipeline). Ideal speedup = 2 / 0.6 = 3.33x.
- Registers x0-x31 (ABI names allowed); x0 never creates a dependency.

## What changed from v1

| v1 | v2 |
|---|---|
| ADD/SUB dependency at distance 1 = 1 stall without forwarding | 2 CC, as in the notes |
| stalls added up independently (over-counted) | cycle-by-cycle timing, earlier stalls count |
| any load followed by a use stalled, even `sw` data | store data from a load uses path C, no stall |
| reordering changed the program result in 75% of the cases | 0 of 20,000 changed (checked by executing) |
| CPI included the 4 fill cycles (best 1.4) | CPI = (CC - 4) / IC (best 1.0) |
| baseline 5 CC per instruction, "% reduction" | single-cycle CPI = 1 at 2 ns; speedup in x |
| registers R1-R5, LW also read rs2 | RISC-V x0-x31, LW reads only its base |
| no branches | 5 control hazard solutions on real loop programs |

With 50,000 rounds of 10 instructions (dependency 0.5), v1 reported average stalls of
6.92 / 1.22 / 0.24 (no forwarding / forwarding / reordering). v2 gives
5.03 / 0.60 / 0.19 CC, plus 2.98 CC for "rearrange without forwarding".
