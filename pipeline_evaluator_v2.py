#!/usr/bin/env python3
"""
pipeline_evaluator_v2.py - 5-stage RISC-V pipeline simulator (IM  Reg  ALU  DM  Reg)

Version 2 follows the CS 5375 class notes (Topics 1-3):

  * Stages are named as in the notes: IM, Reg, ALU, DM, Reg.
  * The register file is written in the first half of a clock cycle and read in
    the second half, so an instruction may read a value in the same cycle in
    which it is written.
  * CPI = (CC needed - 4) / number of instructions        (Topic 3)
  * Penalty = number of stall clock cycles (CC)
  * Execution time = IC x CPI x T_clk; speedup is a ratio of execution times
    against a single-cycle processor (CPI = 1, T_clk = 2 ns vs 0.6 ns).
  * Data hazards (RAW) are solved by
        Solution 1: insert nop / stall            -> PipelineProcessorWithoutForwarding
        Solution 2: stall after rearrange         -> ReorderingWithoutForwarding
        Solution 3: forwarding hardware (A, B, C) -> PipelineProcessorWithForwarding
        (extra) forwarding + rearrange            -> ForwardingWithReordering
  * Forwarding paths:
        Path B: ALU output -> ALU input of the next instruction
        Path A: DM-stage output -> ALU input (2 instructions later, or a load
                after its 1 CC load-use stall)
        Path C: DM-stage output -> DM input (e.g. lw x4 ... ; sw x4 ...)
  * Control hazards (branches are decided after the ALU, 2 CC penalty):
        stall, predict not taken, predict taken, 1-bit and 2-bit dynamic
        predictors (state diagrams exactly as in the notes).

The simulator first EXECUTES the program (real register and memory values,
so branches go the right way), then times the executed instruction stream
cycle by cycle. Rearranging only moves an instruction when no RAW, WAR or WAW
register dependency and no memory-ordering rule is broken, and the program
results are checked to be identical.

Run it:
    python3 pipeline_evaluator_v2.py            # interactive control panel
    python3 pipeline_evaluator_v2.py --help     # command-line options
"""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import sys
from dataclasses import dataclass, field

# =============================================================================
# 1. RISC-V instruction set (subset from Topic 2)
# =============================================================================
ABI_NAMES = {"zero": 0, "ra": 1, "sp": 2, "gp": 3, "tp": 4, "t0": 5, "t1": 6, "t2": 7,
             "s0": 8, "fp": 8, "s1": 9}
ABI_NAMES.update({f"a{i}": 10 + i for i in range(8)})       # a0-a7 = x10-x17
ABI_NAMES.update({f"s{i}": 16 + i for i in range(2, 12)})   # s2-s11 = x18-x27
ABI_NAMES.update({f"t{i}": 25 + i for i in range(3, 7)})    # t3-t6 = x28-x31

R_TYPE = {"add", "sub", "and", "or", "xor", "sll", "srl", "sra", "slt", "sltu", "mul"}
I_TYPE = {"addi", "andi", "ori", "xori", "slli", "srli", "srai", "slti", "sltiu"}
LOADS = {"lw"}
STORES = {"sw"}
BRANCHES = {"beq", "bne", "blt", "bge"}
U_TYPE = {"lui"}

CLOCK_SINGLE_CYCLE_NS = 2.0    # 0.5 GHz single-cycle processor (Topic 3 example)
CLOCK_PIPELINE_NS = 0.6        # 5-stage pipeline clock period (Topic 3 example)
PIPELINE_FILL = 4              # CC needed = IC + 4 + penalty

BRANCH_POLICIES = ("stall", "not_taken", "taken", "1bit", "2bit")
BRANCH_POLICY_NAMES = {"stall": "Stall (insert nop)", "not_taken": "Predict NOT taken",
                       "taken": "Predict taken", "1bit": "1-bit dynamic",
                       "2bit": "2-bit dynamic"}


def reg_number(token: str) -> int:
    t = token.strip().lower()
    if t in ABI_NAMES:
        return ABI_NAMES[t]
    if re.fullmatch(r"[xr]\d+", t):
        n = int(t[1:])
        if 0 <= n <= 31:
            return n
    raise ValueError(f"unknown register '{token}'")


def to_s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


@dataclass
class Instruction:
    op: str                    # canonical mnemonic, lower case
    rd: int = 0
    rs1: int = 0
    rs2: int = 0
    imm: int = 0
    target_label: str | None = None
    target: int | None = None  # resolved instruction index (branches)
    text: str = ""             # the instruction as written (for diagrams)
    index: int = 0             # position in the program

    # --- what the instruction reads / writes (x0 never creates a dependency) ---
    @property
    def dest(self) -> int | None:
        if self.op in R_TYPE or self.op in I_TYPE or self.op in LOADS or self.op in U_TYPE:
            return self.rd or None
        return None

    @property
    def alu_sources(self) -> list[int]:
        """Registers the ALU needs (read in the Reg stage)."""
        if self.op in R_TYPE or self.op in BRANCHES:
            srcs = [self.rs1, self.rs2]
        elif self.op in I_TYPE or self.op in LOADS or self.op in STORES:
            srcs = [self.rs1]          # lw / sw: only the base register goes to the ALU
        else:
            srcs = []
        return [r for r in dict.fromkeys(srcs) if r]

    @property
    def store_data(self) -> int | None:
        """The register whose value a store writes to memory (needed in DM)."""
        return (self.rs2 or None) if self.op in STORES else None

    @property
    def all_sources(self) -> list[int]:
        s = list(self.alu_sources)
        if self.store_data and self.store_data not in s:
            s.append(self.store_data)
        return s

    @property
    def is_load(self) -> bool:
        return self.op in LOADS

    @property
    def is_store(self) -> bool:
        return self.op in STORES

    @property
    def is_branch(self) -> bool:
        return self.op in BRANCHES

    def copy(self, **changes) -> "Instruction":
        d = dict(self.__dict__)
        d.update(changes)
        return Instruction(**d)


@dataclass
class Program:
    instructions: list[Instruction]
    labels: dict[str, int] = field(default_factory=dict)
    init_regs: dict[int, int] = field(default_factory=dict)
    init_mem: dict[int, int] = field(default_factory=dict)
    name: str = "program"

    def __len__(self):
        return len(self.instructions)

    def with_instructions(self, instructions: list[Instruction], suffix: str = "") -> "Program":
        return Program([ins.copy(index=i) for i, ins in enumerate(instructions)],
                       dict(self.labels), dict(self.init_regs), dict(self.init_mem),
                       self.name + suffix)

    def listing(self) -> str:
        inv = {}
        for lab, idx in self.labels.items():
            inv.setdefault(idx, []).append(lab)
        lines = []
        for i, ins in enumerate(self.instructions):
            lab = ",".join(inv.get(i, []))
            lines.append(f"  I{i + 1:<3} {(lab + ':') if lab else '':<10} {ins.text}")
        return "\n".join(lines)


# =============================================================================
# 2. InstructionSetsParser: RISC-V assembly input + random program generator
# =============================================================================
class InstructionSetsParser:
    """Parses RISC-V assembly (Topic 2 syntax) and generates random programs.

    Assembly format:
        label:  add  x15, x10, x12       # comments with '#' or '//'
                lw   t0, 0(a0)
                beq  zero, zero, label
        .reg  a0 = 0x1000                 # initial register value
        .word 0x1000 3 1 4 1 5            # initial memory words from an address
    Pseudo-instructions: nop, mv, li, j, ble, bgt, beqz, bnez.
    """

    def __init__(self):
        self.regs = [f"x{i}" for i in range(5, 15)]   # x5..x14 for random programs

    # -------------------------------------------------------------- parsing
    def parse(self, source: str, name: str = "program") -> Program:
        instructions: list[Instruction] = []
        labels: dict[str, int] = {}
        init_regs: dict[int, int] = {}
        init_mem: dict[int, int] = {}
        for line_no, raw in enumerate(source.splitlines(), 1):
            line = raw.split("#")[0].split("//")[0].strip()
            if not line:
                continue
            try:
                if line.startswith(".reg"):
                    m = re.fullmatch(r"\.reg\s+(\S+)\s*=\s*(\S+)", line)
                    init_regs[reg_number(m.group(1))] = int(m.group(2), 0)
                    continue
                if line.startswith(".word"):
                    parts = line.replace(",", " ").split()[1:]
                    addr = int(parts[0], 0)
                    for k, v in enumerate(parts[1:]):
                        init_mem[addr + 4 * k] = int(v, 0)
                    continue
                # labels (possibly several) at the start of the line
                while True:
                    m = re.match(r"^([A-Za-z_][\w.]*)\s*:\s*(.*)$", line)
                    if not m:
                        break
                    if re.fullmatch(r"I\d+", m.group(1)):    # "I1: add ..." lecture style tag
                        line = m.group(2).strip()
                        continue
                    labels[m.group(1)] = len(instructions)
                    line = m.group(2).strip()
                if not line:
                    continue
                ins = self._parse_instruction(line)
                ins.index = len(instructions)
                instructions.append(ins)
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"{name}, line {line_no}: '{raw.strip()}': {e}") from None
        for ins in instructions:
            if ins.target_label is not None:
                if ins.target_label not in labels:
                    raise ValueError(f"{name}: undefined label '{ins.target_label}'")
                ins.target = labels[ins.target_label]
        return Program(instructions, labels, init_regs, init_mem, name)

    def parse_file(self, path: str) -> Program:
        with open(path) as f:
            return self.parse(f.read(), os.path.splitext(os.path.basename(path))[0])

    @staticmethod
    def _parse_instruction(line: str) -> Instruction:
        text = " ".join(line.split())
        parts = line.replace(",", " ").split()
        op, args = parts[0].lower(), parts[1:]

        def mem_operand(tok):
            m = re.fullmatch(r"(-?\w+)?\((\w+)\)", tok)
            if not m:
                raise ValueError(f"expected offset(base), got '{tok}'")
            return int(m.group(1) or "0", 0), reg_number(m.group(2))

        # pseudo-instructions
        if op == "nop":
            return Instruction("addi", 0, 0, 0, 0, text=text)
        if op == "mv":
            return Instruction("addi", reg_number(args[0]), reg_number(args[1]), 0, 0, text=text)
        if op == "li":
            return Instruction("addi", reg_number(args[0]), 0, 0, int(args[1], 0), text=text)
        if op == "j":
            return Instruction("beq", 0, 0, 0, target_label=args[0], text=text)
        if op in ("beqz", "bnez"):
            return Instruction("beq" if op == "beqz" else "bne", 0, reg_number(args[0]), 0,
                               target_label=args[1], text=text)
        if op in ("ble", "bgt"):   # ble a,b,L == bge b,a,L ; bgt a,b,L == blt b,a,L
            return Instruction("bge" if op == "ble" else "blt", 0, reg_number(args[1]),
                               reg_number(args[0]), target_label=args[2], text=text)

        if op in R_TYPE:
            return Instruction(op, reg_number(args[0]), reg_number(args[1]), reg_number(args[2]),
                               text=text)
        if op in I_TYPE:
            return Instruction(op, reg_number(args[0]), reg_number(args[1]), 0, int(args[2], 0),
                               text=text)
        if op in LOADS:
            off, base = mem_operand(args[1])
            return Instruction(op, reg_number(args[0]), base, 0, off, text=text)
        if op in STORES:
            off, base = mem_operand(args[1])
            return Instruction(op, 0, base, reg_number(args[0]), off, text=text)
        if op in BRANCHES:
            return Instruction(op, 0, reg_number(args[0]), reg_number(args[1]),
                               target_label=args[2], text=text)
        if op in U_TYPE:
            return Instruction(op, reg_number(args[0]), 0, 0, int(args[1], 0), text=text)
        raise ValueError(f"unsupported instruction '{op}'")

    # ------------------------------------------------------- random programs
    def generate_random_program(self, num_instructions=10, dependency_prob=0.5,
                                ops=("add", "sub", "lw", "sw"), rng=None) -> Program:
        """Random straight-line program (no branches).

        With probability `dependency_prob` an instruction reads a register written
        by one of the previous 2 instructions (a RAW dependency at distance 1 or 2).
        Otherwise its sources avoid those registers, so dependency_prob = 0 really
        means no nearby dependencies.
        """
        rng = rng or random
        regs = list(range(5, 15))
        recent: list[int] = []
        lines = []
        for _ in range(num_instructions):
            op = rng.choice(ops)
            far = [r for r in regs if r not in recent] or regs
            dep = bool(recent) and rng.random() < dependency_prob
            near = rng.choice(recent) if recent else rng.choice(regs)
            if op in ("add", "sub"):
                rd = rng.choice(regs)
                rs1, rs2 = (near if dep else rng.choice(far)), rng.choice(far)
                if dep and rng.random() < 0.5:
                    rs1, rs2 = rs2, rs1
                lines.append(f"{op} x{rd}, x{rs1}, x{rs2}")
            elif op == "lw":
                rd = rng.choice(regs)
                base = near if dep else rng.choice(far)
                lines.append(f"lw x{rd}, {4 * rng.randint(0, 15)}(x{base})")
            elif op == "sw":
                base, data = rng.choice(far), rng.choice(far)
                if dep:
                    if rng.random() < 0.5:
                        data = near
                    else:
                        base = near
                lines.append(f"sw x{data}, {4 * rng.randint(0, 15)}(x{base})")
                rd = None
            else:
                raise ValueError(op)
            if rd is not None:
                recent.append(rd)
                if len(recent) > 2:
                    recent.pop(0)
        prog = self.parse("\n".join(lines), "random")
        prog.init_regs = {r: 4 * rng.randint(0, 255) for r in regs}
        return prog


# =============================================================================
# 3. Functional execution (real values, so branches and reordering are checked)
# =============================================================================
@dataclass
class ExecutionResult:
    regs: list[int]
    mem: dict[int, int]
    trace: list[tuple[int, bool]]     # (instruction index, branch taken?)

    def state(self):
        return tuple(self.regs), tuple(sorted(self.mem.items()))


def execute(program: Program, max_steps: int = 2_000_000) -> ExecutionResult:
    regs = [0] * 32
    for r, v in program.init_regs.items():
        if r:
            regs[r] = to_s32(v)
    mem = dict(program.init_mem)
    trace: list[tuple[int, bool]] = []
    pc, n = 0, len(program.instructions)
    while 0 <= pc < n:
        if len(trace) >= max_steps:
            raise RuntimeError(f"{program.name}: more than {max_steps} steps (infinite loop?)")
        ins = program.instructions[pc]
        op, a, b = ins.op, regs[ins.rs1], regs[ins.rs2]
        taken = False
        nxt = pc + 1
        if op in R_TYPE:
            v = {"add": a + b, "sub": a - b, "and": a & b, "or": a | b, "xor": a ^ b,
                 "sll": a << (b & 31), "srl": (a & 0xFFFFFFFF) >> (b & 31), "sra": a >> (b & 31),
                 "slt": int(a < b), "sltu": int((a & 0xFFFFFFFF) < (b & 0xFFFFFFFF)),
                 "mul": a * b}[op]
            if ins.rd:
                regs[ins.rd] = to_s32(v)
        elif op in I_TYPE:
            i = ins.imm
            v = {"addi": a + i, "andi": a & i, "ori": a | i, "xori": a ^ i,
                 "slli": a << (i & 31), "srli": (a & 0xFFFFFFFF) >> (i & 31), "srai": a >> (i & 31),
                 "slti": int(a < i), "sltiu": int((a & 0xFFFFFFFF) < (i & 0xFFFFFFFF))}[op]
            if ins.rd:
                regs[ins.rd] = to_s32(v)
        elif op in LOADS:
            if ins.rd:
                regs[ins.rd] = to_s32(mem.get(a + ins.imm, 0))
        elif op in STORES:
            mem[a + ins.imm] = b
        elif op in BRANCHES:
            taken = {"beq": a == b, "bne": a != b, "blt": a < b, "bge": a >= b}[op]
            if taken:
                nxt = ins.target
        elif op in U_TYPE:
            if ins.rd:
                regs[ins.rd] = to_s32(ins.imm << 12)
        trace.append((pc, taken))
        pc = nxt
    return ExecutionResult(regs, mem, trace)


# =============================================================================
# 4. Branch predictors (Topic 3: static and dynamic solutions)
# =============================================================================
class BranchPredictor:
    """stall / not_taken / taken / 1bit / 2bit.

    1-bit: state 1 = predict taken, 0 = predict not taken; it flips on a wrong guess.
    2-bit (state diagram in the notes):
        11 (predict taken):     taken -> 11, not taken -> 10
        10 (predict taken):     taken -> 11, not taken -> 00
        01 (predict not taken): taken -> 11, not taken -> 00
        00 (predict not taken): taken -> 01, not taken -> 00
    Dynamic predictors start in "predict not taken" (0 / 00), one entry per branch.
    """
    TWO_BIT_NEXT = {(3, True): 3, (3, False): 2, (2, True): 3, (2, False): 0,
                    (1, True): 3, (1, False): 0, (0, True): 1, (0, False): 0}

    def __init__(self, policy: str = "stall"):
        if policy not in BRANCH_POLICIES:
            raise ValueError(f"branch policy must be one of {BRANCH_POLICIES}")
        self.policy = policy
        self.table: dict[int, int] = {}

    def predict(self, pc: int) -> bool | None:
        if self.policy == "stall":
            return None
        if self.policy == "not_taken":
            return False
        if self.policy == "taken":
            return True
        state = self.table.get(pc, 0)
        return state == 1 if self.policy == "1bit" else state >= 2

    def update(self, pc: int, taken: bool) -> None:
        if self.policy == "1bit":
            self.table[pc] = 1 if taken else 0
        elif self.policy == "2bit":
            self.table[pc] = self.TWO_BIT_NEXT[(self.table.get(pc, 0), taken)]


# =============================================================================
# 5. Cycle-accurate 5-stage pipeline (IM Reg ALU DM Reg)
# =============================================================================
STAGES = ("IM", "Reg", "ALU", "DM", "Reg")


@dataclass
class InstrTiming:
    ins: Instruction
    im: int            # cycle the instruction is fetched (IM)
    reg: int           # cycle it enters the Reg stage
    alu: int           # cycle in the ALU
    dm: int            # cycle in DM
    wb: int            # cycle of the final Reg (write back)
    data_stall: int = 0
    stall_cause: str = ""      # "load" or "alu"
    branch_penalty: int = 0    # CC lost before this instruction because of a branch
    branch_event: str = ""     # for the branch itself: "taken/not taken, predicted ..."
    forwards: list = field(default_factory=list)   # [(register, path)]


@dataclass
class PipelineResult:
    model: str
    program: Program
    timings: list[InstrTiming]
    forwarding: bool
    branch_policy: str
    clock_ns: float = CLOCK_PIPELINE_NS
    branches: int = 0
    mispredictions: int = 0

    @property
    def ic(self) -> int:
        return len(self.timings)

    @property
    def cc(self) -> int:
        return self.timings[-1].wb if self.timings else 0

    @property
    def penalty(self) -> int:
        return self.cc - self.ic - PIPELINE_FILL if self.timings else 0

    @property
    def data_penalty(self) -> int:
        return sum(t.data_stall for t in self.timings)

    @property
    def load_use_penalty(self) -> int:
        return sum(t.data_stall for t in self.timings if t.stall_cause == "load")

    @property
    def alu_use_penalty(self) -> int:
        return sum(t.data_stall for t in self.timings if t.stall_cause == "alu")

    @property
    def branch_penalty(self) -> int:
        return sum(t.branch_penalty for t in self.timings)

    @property
    def cpi(self) -> float:
        return (self.cc - PIPELINE_FILL) / self.ic if self.ic else 0.0

    @property
    def exec_time_ns(self) -> float:
        return self.ic * self.cpi * self.clock_ns

    @property
    def misprediction_rate(self) -> float:
        return self.mispredictions / self.branches if self.branches else 0.0


def _operand_need(producer: InstrTiming, forwarding: bool) -> int:
    """Earliest ALU cycle for a consumer of an ALU operand written by `producer`."""
    if not forwarding:
        return producer.wb + 1            # must read in Reg at or after the write (cycle wb)
    if producer.ins.is_load:
        return producer.dm + 1            # path A after the load's DM stage
    return producer.alu + 1               # path B from the ALU output


def _store_data_need(producer: InstrTiming, forwarding: bool) -> int:
    """Earliest ALU cycle for a store whose DATA register is written by `producer`."""
    if not forwarding:
        return producer.wb + 1
    # The data is needed in DM; it can arrive by path C, so it never forces a stall.
    avail = (producer.dm + 1) if producer.ins.is_load else (producer.alu + 1)
    return avail - 1


def _operand_path(producer: InstrTiming, consumer_alu: int, forwarding: bool) -> str:
    if not forwarding or consumer_alu - 1 >= producer.wb:
        return "RF"                       # read from the register file, no forwarding
    if not producer.ins.is_load and consumer_alu == producer.alu + 1:
        return "B"
    return "A"


def _store_data_path(producer: InstrTiming, consumer_alu: int, forwarding: bool) -> str:
    if not forwarding or consumer_alu - 1 >= producer.wb:
        return "RF"
    if consumer_alu + 1 == producer.wb:
        return "C"
    if not producer.ins.is_load and consumer_alu == producer.alu + 1:
        return "B"
    return "A"


def time_pipeline(program: Program, forwarding: bool, branch_policy: str = "stall",
                  trace=None, model: str = "") -> PipelineResult:
    """Time the executed instruction stream clock cycle by clock cycle.

    Rules (one instruction enters each stage per cycle, in order):
      * an instruction is fetched (IM) when the previous one moves into Reg;
      * it enters Reg when the previous one moves into the ALU;
      * the hazard-detection unit holds it before the ALU until its operands are
        ready (no forwarding: read in Reg in the same cycle as the producer's
        final Reg; forwarding: paths A / B / C);
      * after a branch, the next correct instruction is fetched right after the
        branch's ALU cycle if the branch was stalled for or mispredicted (2 CC).
    """
    if trace is None:
        trace = execute(program).trace
    predictor = BranchPredictor(branch_policy)
    timings: list[InstrTiming] = []
    last_writer: dict[int, InstrTiming] = {}
    redirect = 0
    branches = mispredictions = 0

    for k, (pc, taken) in enumerate(trace):
        ins = program.instructions[pc]
        if k == 0:
            im, prev_alu = 1, 2
            im_natural = 1
        else:
            prev = timings[-1]
            prev_alu = prev.alu
            im_natural = prev.reg
            im = max(im_natural, redirect)
        reg = max(im + 1, prev_alu)
        alu_natural = max(reg + 1, prev_alu + 1)
        alu_without_branch = max(max(im_natural + 1, prev_alu) + 1, prev_alu + 1)
        branch_pen = alu_natural - alu_without_branch

        need, cause = alu_natural, ""
        for r in ins.alu_sources:
            p = last_writer.get(r)
            if p is not None:
                n = _operand_need(p, forwarding)
                if n > need:
                    need, cause = n, ("load" if p.ins.is_load else "alu")
        if ins.store_data:
            p = last_writer.get(ins.store_data)
            if p is not None:
                n = _store_data_need(p, forwarding)
                if n > need:
                    need, cause = n, ("load" if p.ins.is_load else "alu")
        alu = need
        t = InstrTiming(ins, im, reg, alu, alu + 1, alu + 2, alu - alu_natural, cause, branch_pen)

        for r in ins.alu_sources:
            p = last_writer.get(r)
            if p is not None:
                path = _operand_path(p, alu, forwarding)
                if path != "RF":
                    t.forwards.append((r, path))
        if ins.store_data and last_writer.get(ins.store_data) is not None:
            path = _store_data_path(last_writer[ins.store_data], alu, forwarding)
            if path != "RF":
                t.forwards.append((ins.store_data, path))

        redirect = 0
        if ins.is_branch:
            branches += 1
            guess = predictor.predict(pc)
            predictor.update(pc, taken)
            outcome = "taken" if taken else "not taken"
            if guess is None:
                redirect = alu + 1
                t.branch_event = f"{outcome}, stalled"
            elif guess != taken:
                mispredictions += 1
                redirect = alu + 1
                t.branch_event = f"{outcome}, mispredicted -> flush"
            else:
                t.branch_event = f"{outcome}, predicted correctly"

        if ins.dest:
            last_writer[ins.dest] = t
        timings.append(t)

    res = PipelineResult(model, program, timings, forwarding, branch_policy,
                         branches=branches, mispredictions=mispredictions)
    assert res.penalty == res.data_penalty + res.branch_penalty, "penalty accounting error"
    return res


# =============================================================================
# 6. Safe rearranging (Solution 2: stall after rearrange)
# =============================================================================
def _depends(a: Instruction, b: Instruction) -> bool:
    """True if b (later) must stay after a (earlier)."""
    if a.dest and a.dest in b.all_sources:          # RAW
        return True
    if b.dest and b.dest in a.all_sources:          # WAR
        return True
    if a.dest and a.dest == b.dest:                 # WAW
        return True
    mem_a, mem_b = a.is_load or a.is_store, b.is_load or b.is_store
    if mem_a and mem_b and (a.is_store or b.is_store):   # keep memory order around stores
        return True
    return False


def _block_cycles(block: list[Instruction], forwarding: bool) -> int:
    prog = Program(list(block))
    trace = [(i, False) for i in range(len(block))]
    return time_pipeline(prog, forwarding, "stall", trace).cc if block else 0


def _schedule_block(block: list[Instruction], forwarding: bool) -> list[Instruction]:
    n = len(block)
    if n < 2:
        return list(block)
    preds = [set() for _ in range(n)]
    succs = [set() for _ in range(n)]
    for j in range(n):
        for i in range(j):
            if _depends(block[i], block[j]):
                preds[j].add(i)
                succs[i].add(j)
    height = [1] * n
    for i in reversed(range(n)):
        if succs[i]:
            height[i] = 1 + max(height[s] for s in succs[i])

    scheduled: list[int] = []
    done: set[int] = set()
    # incremental timing state of the scheduled part
    alus, dms, wbs, loads = [], [], [], []
    writer_pos: dict[int, int] = {}

    def alu_if_next(ins: Instruction) -> int:
        natural = (alus[-1] + 1) if alus else 3
        need = natural
        for r in ins.alu_sources:
            if r in writer_pos:
                p = writer_pos[r]
                if not forwarding:
                    need = max(need, wbs[p] + 1)
                else:
                    need = max(need, dms[p] + 1 if loads[p] else alus[p] + 1)
        if ins.store_data and ins.store_data in writer_pos and not forwarding:
            need = max(need, wbs[writer_pos[ins.store_data]] + 1)
        return need

    while len(scheduled) < n:
        ready = [i for i in range(n) if i not in done and preds[i] <= done]
        best = min(ready, key=lambda i: (alu_if_next(block[i]), -height[i], i))
        a = alu_if_next(block[best])
        pos = len(scheduled)
        scheduled.append(best)
        done.add(best)
        alus.append(a)
        dms.append(a + 1)
        wbs.append(a + 2)
        loads.append(block[best].is_load)
        if block[best].dest:
            writer_pos[block[best].dest] = pos
    new_block = [block[i] for i in scheduled]
    # never make a block slower than the original order
    if _block_cycles(new_block, forwarding) >= _block_cycles(block, forwarding):
        return list(block)
    return new_block


def rearrange(program: Program, forwarding: bool) -> Program:
    """Reorder instructions inside each basic block. Branches and labels stay put."""
    ins = program.instructions
    leaders = {0} | set(program.labels.values()) | {i + 1 for i, x in enumerate(ins) if x.is_branch}
    leaders = sorted(l for l in leaders if l < len(ins))
    out: list[Instruction] = []
    for bi, start in enumerate(leaders):
        end = leaders[bi + 1] if bi + 1 < len(leaders) else len(ins)
        block = ins[start:end]
        tail = []
        if block and block[-1].is_branch:
            block, tail = block[:-1], [block[-1]]
        out.extend(_schedule_block(block, forwarding) + tail)
    return program.with_instructions(out, " (rearranged)")


# =============================================================================
# 7. The processor models (class names kept from v1)
# =============================================================================
@dataclass
class SingleCycleResult:
    model: str
    ic: int
    clock_ns: float = CLOCK_SINGLE_CYCLE_NS

    @property
    def cc(self):
        return self.ic

    @property
    def cpi(self):
        return 1.0

    @property
    def penalty(self):
        return 0

    @property
    def exec_time_ns(self):
        return self.ic * self.cpi * self.clock_ns


class SimpleMicroProcessor:
    """Single-cycle processor (baseline): CPI = 1, T_clk = 2 ns (0.5 GHz)."""
    name = "Single-cycle processor (baseline)"

    def __init__(self, program: Program, clock_ns: float = CLOCK_SINGLE_CYCLE_NS, trace=None):
        self.program, self.clock_ns = program, clock_ns
        self.trace = trace

    def run(self) -> SingleCycleResult:
        trace = self.trace if self.trace is not None else execute(self.program).trace
        return SingleCycleResult(self.name, len(trace), self.clock_ns)


class _PipelineModel:
    name = ""
    forwarding = False
    reorder = False

    def __init__(self, program: Program, branch_policy: str = "stall",
                 clock_ns: float = CLOCK_PIPELINE_NS):
        self.original = program
        self.program = rearrange(program, self.forwarding) if self.reorder else program
        self.branch_policy = branch_policy
        self.clock_ns = clock_ns

    def run(self) -> PipelineResult:
        res = time_pipeline(self.program, self.forwarding, self.branch_policy, model=self.name)
        res.clock_ns = self.clock_ns
        return res


class PipelineProcessorWithoutForwarding(_PipelineModel):
    """Solution 1: the hazard-detection unit inserts stalls (nop)."""
    name = "Pipeline without forwarding (stall/nop)"


class ReorderingWithoutForwarding(_PipelineModel):
    """Solution 2: stall after rearrange (no forwarding hardware)."""
    name = "Rearrange without forwarding"
    reorder = True


class PipelineProcessorWithForwarding(_PipelineModel):
    """Solution 3: forwarding hardware, paths A, B, C."""
    name = "Pipeline with forwarding (A/B/C)"
    forwarding = True


class ForwardingWithReordering(_PipelineModel):
    """Extra: forwarding hardware + rearranging."""
    name = "Forwarding + rearrange"
    forwarding = True
    reorder = True


PIPELINE_MODELS = [PipelineProcessorWithoutForwarding, ReorderingWithoutForwarding,
                   PipelineProcessorWithForwarding, ForwardingWithReordering]


def check_rearranging(program: Program) -> bool:
    """True if both rearranged versions compute exactly the same result."""
    ref = execute(program).state()
    return all(execute(rearrange(program, fw)).state() == ref for fw in (False, True))


# =============================================================================
# 8. Timing diagrams (text)
# =============================================================================
def diagram_rows(res: PipelineResult, style: str = "nop"):
    """Rows of a timing diagram: (label, {cycle: stage}, note, kind, timing-or-None).

    style="nop":   stalls are drawn as nop rows and each instruction's stages are
                   contiguous (like "Solution 1: insert nop" in the notes).
    style="stall": each instruction is fetched as early as possible and waits
                   (shown as **) until it can continue (hardware interlock).
    """
    rows = []
    for t in res.timings:
        if style == "nop":
            first_bubble_im = t.alu - 2 - t.data_stall - t.branch_penalty
            for j in range(t.branch_penalty):
                c0 = first_bubble_im + j
                kind = "flush" if res.branch_policy != "stall" else "nop"
                rows.append((kind, {c0 + s: "--" for s in range(5)}, "branch penalty", kind, None))
            for j in range(t.data_stall):
                c0 = first_bubble_im + t.branch_penalty + j
                rows.append(("nop", {c0 + s: "--" for s in range(5)},
                             f"{'load' if t.stall_cause == 'load' else 'ALU'}-use stall", "nop", None))
            cells = {t.alu - 2: "IM", t.alu - 1: "Reg", t.alu: "ALU", t.alu + 1: "DM",
                     t.alu + 2: "Reg"}
        else:
            cells = {t.im: "IM"}
            for c in range(t.im + 1, t.alu - 1):
                cells[c] = "**"
            cells.update({t.alu - 1: "Reg", t.alu: "ALU", t.alu + 1: "DM", t.alu + 2: "Reg"})
        notes = []
        if t.forwards:
            notes.append(", ".join(f"x{r} via path {p}" for r, p in t.forwards))
        if t.branch_event:
            notes.append(t.branch_event)
        rows.append((t.ins.text, cells, "; ".join(notes), "instr", t))
    return rows


def timing_diagram(res: PipelineResult, style: str = "nop", max_cycles: int = 60) -> str:
    """Text timing diagram in the notes' style (see diagram_rows for the styles)."""
    rows = diagram_rows(res, style)
    ncyc = min(res.cc, max_cycles)
    lw = max(14, max(len(r[0]) for r in rows) + 1)
    head = " " * lw + "".join(f"CC{c}".ljust(6) for c in range(1, ncyc + 1))
    out = [head.rstrip()]
    for label, cells, note, _, _ in rows:
        line = label.ljust(lw) + "".join((cells.get(c, "")).ljust(6) for c in range(1, ncyc + 1))
        out.append(line.rstrip() + (f"   <- {note}" if note else ""))
    if res.cc > max_cycles:
        out.append(f"... ({res.cc - max_cycles} more cycles not shown)")
    out.append(f"CC needed = {res.cc}   IC = {res.ic}   CPI = ({res.cc} - 4) / {res.ic} = "
               f"{res.cpi:.2f}   Penalty = {res.penalty} CC")
    return "\n".join(out)


# =============================================================================
# 9. Evaluation engine (random programs, as in v1, now with correct rules)
# =============================================================================
def mean_ci(values):
    n = len(values)
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, 1.96 * math.sqrt(var / n)


class EvaluationEngine:
    """Generates random programs and compares all models."""

    def __init__(self, num_runs=200, num_instructions=10, dep_prob=0.5, seed=2026,
                 branch_policy="stall"):
        self.num_runs, self.num_instructions, self.dep_prob = num_runs, num_instructions, dep_prob
        self.seed, self.branch_policy = seed, branch_policy
        self.parser = InstructionSetsParser()

    def collect(self):
        rng = random.Random(self.seed)
        data = {m.name: {"cc": [], "cpi": [], "pen": [], "time": [], "load": [], "alu": []}
                for m in PIPELINE_MODELS}
        single_time, wrong, deps, total = [], 0, 0, 0
        for _ in range(self.num_runs):
            prog = self.parser.generate_random_program(self.num_instructions, self.dep_prob, rng=rng)
            single_time.append(SimpleMicroProcessor(prog).run().exec_time_ns)
            deps += measured_dependencies(prog)
            total += len(prog) - 1
            ref = execute(prog).state()
            for model in PIPELINE_MODELS:
                m = model(prog, self.branch_policy)
                if m.reorder and execute(m.program).state() != ref:
                    wrong += 1
                r = m.run()
                d = data[model.name]
                d["cc"].append(r.cc)
                d["cpi"].append(r.cpi)
                d["pen"].append(r.penalty)
                d["time"].append(r.exec_time_ns)
                d["load"].append(r.load_use_penalty)
                d["alu"].append(r.alu_use_penalty)
        return data, single_time, wrong, deps / max(total, 1)

    def evaluate(self):
        data, single_time, wrong, dep_rate = self.collect()
        ic = self.num_instructions
        avg_single = sum(single_time) / len(single_time)
        w = 108
        print("\n" + "=" * w)
        print(" Pipeline Processor Simulator v2 - Comprehensive Performance Evaluation")
        print(f" • Instruction Set Size (Fixed):            {ic} instructions (add, sub, lw, sw)")
        print(f" • Inter-instruction Dependency Prob:       {int(self.dep_prob * 100)}%"
              f"   (measured RAW on previous 2 instructions: {100 * dep_rate:.1f}%)")
        print(f" • InstructionSetsParser Generation Count:  {self.num_runs} rounds   (seed {self.seed})")
        print(f" • CPI = (CC needed - 4) / IC;  T_clk: single-cycle {CLOCK_SINGLE_CYCLE_NS} ns, "
              f"pipeline {CLOCK_PIPELINE_NS} ns")
        print("=" * w)
        print(f"0. {SimpleMicroProcessor.name:<42} CC = {ic:6.2f} | CPI = 1.00 | "
              f"Penalty =  N/A | Time = {avg_single:6.2f} ns")
        for i, model in enumerate(PIPELINE_MODELS, 1):
            d = data[model.name]
            cc, cpi, pen = (sum(d[k]) / self.num_runs for k in ("cc", "cpi", "pen"))
            t = sum(d["time"]) / self.num_runs
            print(f"{i}. {model.name:<42} CC = {cc:6.2f} | CPI = {cpi:4.2f} | "
                  f"Penalty = {pen:4.2f} CC | Time = {t:6.2f} ns")
        print("-" * w)
        print("[Speedup vs single-cycle processor = single-cycle execution time / pipeline "
              f"execution time]   (ideal = {CLOCK_SINGLE_CYCLE_NS / CLOCK_PIPELINE_NS:.2f}x)")
        for model in PIPELINE_MODELS:
            t = sum(data[model.name]["time"]) / self.num_runs
            print(f"• {model.name:<45} {avg_single / t:5.2f}x")
        print("-" * w)
        print(f"Rearranging check: {wrong} of {2 * self.num_runs} rearranged programs changed the "
              "program result" + ("  -> OK, all identical" if wrong == 0 else "  -> ERROR"))
        print("=" * w + "\n")
        return data


def measured_dependencies(prog: Program) -> int:
    """Instructions that read a register written by one of the previous 2."""
    cnt = 0
    ins = prog.instructions
    for i in range(1, len(ins)):
        writers = {ins[k].dest for k in (i - 1, i - 2) if k >= 0 and ins[k].dest}
        if writers & set(ins[i].all_sources):
            cnt += 1
    return cnt


# =============================================================================
# 10. Built-in programs: lecture examples (Topic 3) and loop programs (Topic 2)
# =============================================================================
HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM_DIR = os.path.join(HERE, "programs")


def load_program(name: str) -> Program:
    """Load programs/<name>.s (also searches programs/lecture and programs/loops)."""
    for sub in ("", "lecture", "loops"):
        path = os.path.join(PROGRAM_DIR, sub, name + ".s")
        if os.path.exists(path):
            return InstructionSetsParser().parse_file(path)
    if os.path.exists(name):
        return InstructionSetsParser().parse_file(name)
    raise FileNotFoundError(name)


def list_programs(sub: str) -> list[str]:
    d = os.path.join(PROGRAM_DIR, sub)
    return sorted(f[:-2] for f in os.listdir(d) if f.endswith(".s")) if os.path.isdir(d) else []


def compare_models(program: Program, branch_policy="stall", diagrams=True, style="nop"):
    single = SimpleMicroProcessor(program).run()
    print(f"\nProgram: {program.name}")
    print(program.listing())
    for model in PIPELINE_MODELS:
        m = model(program, branch_policy)
        r = m.run()
        print("\n" + "-" * 90)
        print(f"{m.name}" + (f"   [branches: {BRANCH_POLICY_NAMES[branch_policy]}]"
                             if r.branches else ""))
        if m.reorder:
            same = execute(m.program).state() == execute(program).state()
            print("Rearranged order (result identical: " + ("yes" if same else "NO") + "):")
            print(m.program.listing())
        if diagrams:
            print(timing_diagram(r, style))
        else:
            print(f"CC needed = {r.cc}  IC = {r.ic}  CPI = {r.cpi:.2f}  Penalty = {r.penalty} CC")
        print(f"Execution time = {r.ic} x {r.cpi:.2f} x {r.clock_ns} ns = {r.exec_time_ns:.2f} ns"
              f"   speedup vs single-cycle ({single.exec_time_ns:.1f} ns) = "
              f"{single.exec_time_ns / r.exec_time_ns:.2f}x" if r.exec_time_ns else "")
        if r.branches:
            print(f"Branches: {r.branches}, mispredicted/stalled: "
                  f"{r.mispredictions if branch_policy != 'stall' else r.branches}, "
                  f"branch penalty = {r.branch_penalty} CC, data penalty = {r.data_penalty} CC")


def branch_report(program: Program, model=PipelineProcessorWithForwarding):
    print(f"\nBranch prediction on '{program.name}' ({model.name})")
    print(f"{'Policy':<22}{'CC':>8}{'IC':>7}{'CPI':>7}{'Branches':>10}{'Mispred.':>10}"
          f"{'Rate':>8}{'Br. pen.':>10}")
    for pol in BRANCH_POLICIES:
        r = model(program, pol).run()
        mis = r.branches if pol == "stall" else r.mispredictions
        rate = "  -" if pol == "stall" else f"{100 * r.misprediction_rate:5.1f}%"
        print(f"{BRANCH_POLICY_NAMES[pol]:<22}{r.cc:>8}{r.ic:>7}{r.cpi:>7.2f}{r.branches:>10}"
              f"{mis:>10}{rate:>8}{r.branch_penalty:>10}")


# =============================================================================
# 11. Control panel
# =============================================================================
def ask(prompt, default):
    try:
        s = input(f"{prompt} (default {default}): ").strip()
        return type(default)(s) if s else default
    except ValueError:
        print(f"[Notice] Invalid input, using default {default}.")
        return default
    except EOFError:
        return default


def interactive():
    print("=== Pipeline Simulator Control Panel (v2) ===")
    print("1. Random program evaluation (compare all models)")
    print("2. Lecture examples with timing diagrams (Topic 3)")
    print("3. Branch prediction on Topic 2 loop programs")
    print("4. Run your own RISC-V assembly file")
    choice = ask("Choose", 1)
    if choice == 1:
        runs = ask("Enter [InstructionSetsParser Generation Count]", 200)
        n = ask("Instructions per program", 10)
        p = ask("Dependency probability (0-1)", 0.5)
        EvaluationEngine(runs, n, p).evaluate()
    elif choice == 2:
        for name in list_programs("lecture"):
            compare_models(load_program(name))
    elif choice == 3:
        for name in list_programs("loops"):
            branch_report(load_program(name))
    elif choice == 4:
        path = ask("Path to .s file", "programs/loops/for_sum.s")
        pol = ask("Branch policy (stall, not_taken, taken, 1bit, 2bit)", "stall")
        compare_models(InstructionSetsParser().parse_file(path), pol)


def main(argv=None):
    if argv is None and len(sys.argv) == 1:
        interactive()
        return 0
    ap = argparse.ArgumentParser(description="5-stage RISC-V pipeline simulator (v2)")
    ap.add_argument("--rounds", type=int, help="random evaluation with this many programs")
    ap.add_argument("--instructions", type=int, default=10)
    ap.add_argument("--dep", type=float, default=0.5, help="dependency probability")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--lecture", action="store_true", help="run all lecture examples")
    ap.add_argument("--loops", action="store_true", help="branch prediction on loop programs")
    ap.add_argument("--file", help="run a RISC-V assembly file")
    ap.add_argument("--branch", default="stall", choices=BRANCH_POLICIES)
    ap.add_argument("--style", default="nop", choices=("nop", "stall"),
                    help="timing diagram style")
    args = ap.parse_args(argv)
    if args.rounds:
        EvaluationEngine(args.rounds, args.instructions, args.dep, args.seed).evaluate()
    if args.lecture:
        for name in list_programs("lecture"):
            compare_models(load_program(name), style=args.style)
    if args.loops:
        for name in list_programs("loops"):
            branch_report(load_program(name))
    if args.file:
        compare_models(InstructionSetsParser().parse_file(args.file), args.branch, style=args.style)
    if not (args.rounds or args.lecture or args.loops or args.file):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
