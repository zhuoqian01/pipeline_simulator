#!/usr/bin/env python3
"""
run_experiments_v2.py - all experiments and graphs for the pipeline project.

    python3 run_experiments_v2.py            # everything (about 1-2 minutes)
    python3 run_experiments_v2.py --only 1 5 # just some experiments
    python3 run_experiments_v2.py --quick    # fewer rounds, for a fast check

Writes figures/*.png (slides/video) + figures/*.pdf (report), results/*.csv
and results/summary.md.

  1. Timing diagrams of the lecture examples (IM Reg ALU DM Reg, nops, paths A/B/C)
  2. CPI vs. dependency probability
  3. Penalty breakdown (ALU-use, load-use, branch) as parts of the CPI
  4. Speedup over the single-cycle processor (execution time = IC x CPI x T_clk)
  5. Branch prediction: CPI and misprediction rate on the Topic 2 loop programs
  6. Convergence of the averages vs. number of rounds (95% confidence interval)
"""

import argparse
import csv
import os
import random
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from pipeline_evaluator_v2 import (BRANCH_POLICIES, BRANCH_POLICY_NAMES,  # noqa: E402
                                   CLOCK_PIPELINE_NS, CLOCK_SINGLE_CYCLE_NS, PIPELINE_MODELS,
                                   ForwardingWithReordering, InstructionSetsParser,
                                   PipelineProcessorWithForwarding, ReorderingWithoutForwarding,
                                   PipelineProcessorWithoutForwarding, SimpleMicroProcessor,
                                   diagram_rows, execute, load_program, mean_ci)

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "figures")
RES = os.path.join(HERE, "results")
SEED = 2026
LOOPS = ["for_sum", "array_sum", "while_loop", "nested_loop", "bubble_sort"]
LOOP_LABELS = {"for_sum": "for loop\n(sum i)", "array_sum": "array sum", "while_loop": "while loop",
               "nested_loop": "nested loop\n(8x8)", "bubble_sort": "bubble sort"}
SHORT = {PipelineProcessorWithoutForwarding.name: "No forwarding\n(stall/nop)",
         ReorderingWithoutForwarding.name: "Rearrange,\nno forwarding",
         PipelineProcessorWithForwarding.name: "Forwarding\n(A/B/C)",
         ForwardingWithReordering.name: "Forwarding +\nrearrange"}
COLORS = ["#d62728", "#ff7f0e", "#1f77b4", "#2ca02c", "#9467bd"]
STAGE_COLORS = {"IM": "#cfe2f3", "Reg": "#d9ead3", "ALU": "#fce5cd", "DM": "#e6d5f0", "**": "#f2f2f2"}

plt.rcParams.update({"figure.dpi": 100, "savefig.dpi": 200, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False,
                     "legend.fontsize": 8.5})
PARSER = InstructionSetsParser()
SUMMARY: list[str] = []


def save(fig, name):
    os.makedirs(FIG, exist_ok=True)
    fig.savefig(os.path.join(FIG, name + ".png"), bbox_inches="tight")
    fig.savefig(os.path.join(FIG, name + ".pdf"), bbox_inches="tight")
    plt.close(fig)


def write_csv(name, rows):
    os.makedirs(RES, exist_ok=True)
    with open(os.path.join(RES, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


# ------------------------------------------------------------------ graph 1
def draw_timing(ax, res, title):
    rows = diagram_rows(res, "nop")
    n, ncyc = len(rows), res.cc
    ax.set_xlim(-0.2, ncyc + 0.2)
    ax.set_ylim(n + 0.2, -1.1)
    ax.axis("off")
    for c in range(1, ncyc + 1):
        ax.text(c - 0.5, -0.6, f"CC{c}", ha="center", va="center", fontsize=7.5, color="#2a7d2a")
    centers = {}
    for y, (label, cells, note, kind, t) in enumerate(rows):
        if kind == "instr":
            ax.text(-0.3, y + 0.5, label, ha="right", va="center", fontsize=8.5, family="monospace")
            for c, stage in cells.items():
                box = FancyBboxPatch((c - 0.95, y + 0.12), 0.9, 0.76,
                                     boxstyle="round,pad=0.01,rounding_size=0.15",
                                     fc=STAGE_COLORS.get(stage, "#d9ead3"), ec="#335", lw=0.8)
                ax.add_patch(box)
                ax.text(c - 0.5, y + 0.5, stage, ha="center", va="center", fontsize=7.5)
            centers[id(t)] = (y, t)
        else:
            ax.text(-0.3, y + 0.5, label, ha="right", va="center", fontsize=8.5, color="#777",
                    family="monospace", style="italic")
            cs = sorted(cells)
            ax.plot([cs[0] - 0.9, cs[-1] - 0.1], [y + 0.5] * 2, color="#8ab", lw=1.2, ls="--")
            for c in cs:
                ax.plot(c - 0.5, y + 0.5, "o", ms=4, mfc="white", mec="#8ab")
        if note:
            ax.text(ncyc + 0.3, y + 0.5, note, ha="left", va="center", fontsize=7.5, color="#b45f06")
    # forwarding arrows: end of producer stage -> start of consumer stage
    timeline = [r[4] for r in rows if r[3] == "instr"]
    for k, t in enumerate(timeline):
        for reg, path in t.forwards:
            prod = next(p for p in reversed(timeline[:k]) if p.ins.dest == reg)
            py, cy = centers[id(prod)][0], centers[id(t)][0]
            src_c = prod.alu if path == "B" else prod.dm
            dst_c = t.alu if path in ("A", "B") else t.dm
            ax.annotate("", xy=(dst_c - 0.9, cy + 0.3), xytext=(src_c - 0.1, py + 0.7),
                        arrowprops=dict(arrowstyle="->", color="#e06666", lw=1.6))
            ax.text((src_c + dst_c) / 2 - 0.25, (py + cy) / 2 + 0.5, f"{path}", fontsize=8,
                    color="#cc0000", weight="bold", ha="center")
    ax.set_title(f"{title}\nCC needed = {res.cc}, CPI = ({res.cc} - 4)/{res.ic} = {res.cpi:.2f}, "
                 f"penalty = {res.penalty} CC", fontsize=9.5, loc="left")


def exp1():
    cases = [("ex3_lw_sub_addi_sw_ori", [PipelineProcessorWithoutForwarding,
                                         ReorderingWithoutForwarding,
                                         PipelineProcessorWithForwarding]),
             ("ex2_add_sub_and_or", [PipelineProcessorWithoutForwarding,
                                     PipelineProcessorWithForwarding]),
             ("ex4_add_lw_sw", [PipelineProcessorWithoutForwarding,
                                PipelineProcessorWithForwarding])]
    rows = []
    for name, models in cases:
        prog = load_program(name)
        heights = [len(diagram_rows(m(prog).run())) for m in models]
        fig, axes = plt.subplots(len(models), 1, figsize=(9.5, sum(heights) * 0.42 + 1.4 * len(models)),
                                 gridspec_kw={"height_ratios": [h + 2 for h in heights]})
        axes = [axes] if len(models) == 1 else axes
        for ax, m in zip(axes, models):
            r = m(prog).run()
            draw_timing(ax, r, m.name)
            rows.append([name, m.name, r.cc, r.penalty, f"{r.cpi:.2f}"])
        fig.tight_layout()
        save(fig, f"exp1_timing_{name}")
    write_csv("exp1_lecture_examples.csv",
              [dict(zip(["program", "model", "cc", "penalty", "cpi"], r)) for r in rows])
    SUMMARY.extend(["## Graph 1 - lecture examples (all match the class notes)", ""] +
                   md_table(["Program", "Model", "CC needed", "Penalty (CC)", "CPI"], rows) + [""])


# ------------------------------------------------------------------ graph 2
def exp2(rounds, length=20):
    probs = [i / 10 for i in range(11)]
    rows = []
    for p in probs:
        rng = random.Random(SEED + int(p * 100))
        acc = {m.name: [] for m in PIPELINE_MODELS}
        for _ in range(rounds):
            prog = PARSER.generate_random_program(length, p, rng=rng)
            for m in PIPELINE_MODELS:
                acc[m.name].append(m(prog).run().cpi)
        for m in PIPELINE_MODELS:
            mu, ci = mean_ci(acc[m.name])
            rows.append({"dep_prob": p, "model": m.name, "cpi": mu, "ci95": ci})
    write_csv("exp2_cpi_vs_dependency.csv", rows)
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    for col, m in zip(COLORS, PIPELINE_MODELS):
        ys = [r["cpi"] for r in rows if r["model"] == m.name]
        ax.plot(probs, ys, marker="o", color=col, label=m.name)
    ax.axhline(1.0, color="gray", ls="--", lw=1)
    ax.text(0.62, 0.985, "ideal CPI = 1", color="gray", fontsize=8, va="top")
    ax.set_xlabel("Dependency probability")
    ax.set_ylabel("CPI = (CC - 4) / IC")
    ax.set_title(f"Graph 2: CPI vs. dependency probability ({length}-instruction programs, "
                 f"{rounds} per point)", fontsize=10)
    ax.legend(loc="upper left")
    save(fig, "exp2_cpi_vs_dependency")
    tab = []
    for p in (0.0, 0.5, 1.0):
        tab.append([p] + [f"{next(r['cpi'] for r in rows if r['model'] == m.name and r['dep_prob'] == p):.3f}"
                          for m in PIPELINE_MODELS])
    SUMMARY.extend([f"## Graph 2 - CPI vs dependency probability ({rounds} programs of {length} "
                    "instructions per point)", ""] +
                   md_table(["dep. prob."] + [m.name for m in PIPELINE_MODELS], tab) + [""])


# ------------------------------------------------------------------ graph 3
def exp3(rounds, length=20):
    rng = random.Random(SEED)
    progs = [PARSER.generate_random_program(length, 0.5, rng=rng) for _ in range(rounds)]
    loops = [load_program(n) for n in LOOPS]
    rows = []
    for m in PIPELINE_MODELS:
        for group, plist in (("random", progs), ("loops", loops)):
            ic = alu = load = br = 0
            for p in plist:
                r = m(p, "stall").run()
                ic += r.ic
                alu += r.alu_use_penalty
                load += r.load_use_penalty
                br += r.branch_penalty
            rows.append({"group": group, "model": m.name, "ic": ic, "alu_use": alu / ic,
                         "load_use": load / ic, "branch": br / ic})
    write_csv("exp3_penalty_breakdown.csv", rows)
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0), sharey=True)
    titles = {"random": f"(a) Random programs, dep. prob. 0.5\n({rounds} programs, no branches)",
              "loops": "(b) Topic 2 loop programs\n(5 programs, branches: stall)"}
    for ax, group in zip(axes, ("random", "loops")):
        sub = [r for r in rows if r["group"] == group]
        xs = range(len(sub))
        base = [1.0] * len(sub)
        parts = [("Ideal (1 CC / instr.)", base, "#cccccc"),
                 ("ALU-use stalls", [r["alu_use"] for r in sub], "#ff7f0e"),
                 ("Load-use stalls", [r["load_use"] for r in sub], "#1f77b4"),
                 ("Branch penalty", [r["branch"] for r in sub], "#9467bd")]
        bottom = [0.0] * len(sub)
        for label, vals, col in parts:
            ax.bar(xs, vals, 0.6, bottom=bottom, color=col, label=label)
            bottom = [b + v for b, v in zip(bottom, vals)]
        for x, b in zip(xs, bottom):
            ax.text(x, b + 0.02, f"{b:.2f}", ha="center", fontsize=8)
        ax.set_xticks(list(xs), [SHORT[r["model"]] for r in sub], fontsize=7.8)
        ax.set_title(titles[group], fontsize=9.5)
    axes[0].set_ylabel("CPI  (= 1 + penalty CC per instruction)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 0.0), frameon=False)
    fig.suptitle("Graph 3: Where the penalty comes from", fontsize=10.5)
    fig.tight_layout()
    save(fig, "exp3_penalty_breakdown")
    SUMMARY.extend(["## Graph 3 - penalty breakdown (CC per instruction; CPI = 1 + sum)", ""] +
                   md_table(["Group", "Model", "ALU-use", "Load-use", "Branch", "CPI"],
                            [[r["group"], r["model"], f"{r['alu_use']:.3f}", f"{r['load_use']:.3f}",
                              f"{r['branch']:.3f}",
                              f"{1 + r['alu_use'] + r['load_use'] + r['branch']:.3f}"]
                             for r in rows]) + [""])


# ------------------------------------------------------------------ graph 4
def exp4(rounds, length=20):
    rng = random.Random(SEED + 1)
    progs = [PARSER.generate_random_program(length, 0.5, rng=rng) for _ in range(rounds)]
    workloads = [("Random\n(dep. 0.5)", progs)] + [(LOOP_LABELS[n], [load_program(n)]) for n in LOOPS]
    configs = [(m.name, m, "stall") for m in PIPELINE_MODELS] + \
              [("Forwarding + rearrange + 2-bit predictor", ForwardingWithReordering, "2bit")]
    rows = []
    for wname, plist in workloads:
        single = sum(SimpleMicroProcessor(p).run().exec_time_ns for p in plist)
        for cname, model, pol in configs:
            t = sum(model(p, pol).run().exec_time_ns for p in plist)
            rows.append({"workload": wname.replace("\n", " "), "config": cname,
                         "single_ns": single / len(plist), "pipeline_ns": t / len(plist),
                         "speedup": single / t})
    write_csv("exp4_speedup.csv", rows)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    width = 0.15
    for i, (cname, _, _) in enumerate(configs):
        ys = [r["speedup"] for r in rows if r["config"] == cname]
        xs = [x + (i - 2) * width for x in range(len(workloads))]
        bars = ax.bar(xs, ys, width, color=COLORS[i], label=cname)
        ax.bar_label(bars, fmt="%.2f", fontsize=6, padding=1, rotation=90)
    ideal = CLOCK_SINGLE_CYCLE_NS / CLOCK_PIPELINE_NS
    ax.axhline(ideal, color="gray", ls="--", lw=1)
    ax.text(len(workloads) - 0.5, ideal + 0.05, f"ideal = 2 ns / 0.6 ns = {ideal:.2f}x",
            ha="right", fontsize=8, color="gray")
    ax.set_xticks(range(len(workloads)), [w for w, _ in workloads], fontsize=8.5)
    ax.set_ylabel("Speedup vs. single-cycle (x)")
    ax.set_ylim(0, ideal + 0.6)
    ax.set_title("Graph 4: Speedup = single-cycle execution time / pipeline execution time "
                 "(execution time = IC x CPI x T_clk)", fontsize=10)
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.17), frameon=False)
    save(fig, "exp4_speedup")
    SUMMARY.extend(["## Graph 4 - speedup vs single-cycle processor (x)", ""] +
                   md_table(["Workload"] + [c for c, _, _ in configs],
                            [[w.replace("\n", " ")] + [f"{r['speedup']:.2f}" for r in rows
                                                       if r["workload"] == w.replace("\n", " ")]
                             for w, _ in workloads]) + [""])


# ------------------------------------------------------------------ graph 5
def exp5():
    rows = []
    for n in LOOPS:
        prog = load_program(n)
        for pol in BRANCH_POLICIES:
            r = PipelineProcessorWithForwarding(prog, pol).run()
            rows.append({"program": n, "policy": pol, "cc": r.cc, "ic": r.ic, "cpi": r.cpi,
                         "branches": r.branches,
                         "mispredictions": r.branches if pol == "stall" else r.mispredictions,
                         "mispred_rate": 1.0 if pol == "stall" else r.misprediction_rate,
                         "branch_penalty": r.branch_penalty})
    write_csv("exp5_branch_prediction.csv", rows)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.0))
    width = 0.16
    for i, pol in enumerate(BRANCH_POLICIES):
        sub = [r for r in rows if r["policy"] == pol]
        xs = [x + (i - 2) * width for x in range(len(LOOPS))]
        ax1.bar(xs, [r["cpi"] for r in sub], width, color=COLORS[i], label=BRANCH_POLICY_NAMES[pol])
        if pol != "stall":
            b = ax2.bar([x + (i - 2.5) * width for x in range(len(LOOPS))],
                        [100 * r["mispred_rate"] for r in sub], width, color=COLORS[i],
                        label=BRANCH_POLICY_NAMES[pol])
            ax2.bar_label(b, fmt="%.0f", fontsize=6.5, padding=1)
    for ax in (ax1, ax2):
        ax.set_xticks(range(len(LOOPS)), [LOOP_LABELS[n] for n in LOOPS], fontsize=8)
    ax1.set_ylabel("CPI = (CC - 4) / IC")
    ax1.set_ylim(0.8, None)
    ax1.set_title("(a) CPI (pipeline with forwarding)", fontsize=9.5)
    ax2.set_ylabel("Misprediction rate (%)")
    ax2.set_title("(b) Misprediction rate (each wrong guess costs 2 CC)", fontsize=9.5)
    h, l = ax1.get_legend_handles_labels()
    fig.legend(h, l, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 0.0), frameon=False)
    fig.suptitle("Graph 5: Control hazard solutions on the Topic 2 loop programs", fontsize=10.5)
    fig.tight_layout()
    save(fig, "exp5_branch_prediction")
    tab = []
    for n in LOOPS:
        sub = {r["policy"]: r for r in rows if r["program"] == n}
        tab.append([n, sub["stall"]["ic"], sub["stall"]["branches"]] +
                   [f"{sub[p]['cpi']:.2f} ({sub[p]['mispredictions']})" for p in BRANCH_POLICIES])
    SUMMARY.extend(["## Graph 5 - branch prediction, CPI (wrong guesses / stalls) with forwarding", ""] +
                   md_table(["Program", "IC", "Branches"] + [BRANCH_POLICY_NAMES[p] for p in BRANCH_POLICIES],
                            tab) + [""])


# ------------------------------------------------------------------ graph 6
def exp6(max_rounds, length=10):
    rng = random.Random(SEED)
    pens = {m.name: [] for m in PIPELINE_MODELS}
    for _ in range(max_rounds):
        prog = PARSER.generate_random_program(length, 0.5, rng=rng)
        for m in PIPELINE_MODELS:
            pens[m.name].append(m(prog).run().penalty)
    checkpoints = [n for n in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000)
                   if n <= max_rounds]
    rows = []
    for m in PIPELINE_MODELS:
        for n in checkpoints:
            mu, ci = mean_ci(pens[m.name][:n])
            rows.append({"model": m.name, "rounds": n, "mean_penalty": mu, "ci95": ci})
    write_csv("exp6_convergence.csv", rows)
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    for col, m in zip(COLORS, PIPELINE_MODELS):
        sub = [r for r in rows if r["model"] == m.name]
        xs = [r["rounds"] for r in sub]
        mu = [r["mean_penalty"] for r in sub]
        lo = [r["mean_penalty"] - r["ci95"] for r in sub]
        hi = [r["mean_penalty"] + r["ci95"] for r in sub]
        ax.plot(xs, mu, marker="o", ms=3.5, color=col, label=m.name)
        ax.fill_between(xs, lo, hi, color=col, alpha=0.18)
    ax.set_xscale("log")
    ax.set_xlabel("Number of rounds (random programs)")
    ax.set_ylabel("Average penalty (CC per program)")
    ax.set_title(f"Graph 6: Convergence with 95% confidence interval ({length} instructions, "
                 "dep. 0.5)", fontsize=10)
    ax.legend(loc="upper right")
    save(fig, "exp6_convergence")
    tab = [[m.name] + [f"{r['mean_penalty']:.3f} ± {r['ci95']:.3f}" for r in rows
                       if r["model"] == m.name and r["rounds"] in (100, 1000, max_rounds)]
           for m in PIPELINE_MODELS]
    SUMMARY.extend([f"## Graph 6 - convergence (mean penalty ± 95% CI, {length}-instruction programs)",
                    ""] + md_table(["Model"] + [str(n) for n in (100, 1000, max_rounds)
                                                if n in checkpoints], tab) + [""])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--only", type=int, nargs="+", choices=range(1, 7))
    ap.add_argument("--quick", action="store_true", help="fewer rounds (fast check)")
    args = ap.parse_args()
    rounds = 300 if args.quick else 2000
    conv = 2000 if args.quick else 50000
    todo = args.only or [1, 2, 3, 4, 5, 6]
    jobs = {1: exp1, 2: lambda: exp2(rounds), 3: lambda: exp3(rounds), 4: lambda: exp4(rounds),
            5: exp5, 6: lambda: exp6(conv)}
    SUMMARY.extend(["# Results summary (pipeline_evaluator_v2)", "",
                    f"Random programs use seed {SEED}. CPI = (CC needed - 4) / IC. "
                    f"T_clk: single-cycle {CLOCK_SINGLE_CYCLE_NS} ns, pipeline {CLOCK_PIPELINE_NS} ns.",
                    ""])
    t0 = time.time()
    for k in todo:
        t = time.time()
        print(f"Graph {k} ...", end=" ", flush=True)
        jobs[k]()
        print(f"done ({time.time() - t:.1f} s)")
    if not args.only:
        with open(os.path.join(RES, "summary.md"), "w") as f:
            f.write("\n".join(SUMMARY) + "\n")
        print("Summary: results/summary.md")
    print(f"Finished in {time.time() - t0:.1f} s. Figures in figures/, data in results/.")


if __name__ == "__main__":
    main()
