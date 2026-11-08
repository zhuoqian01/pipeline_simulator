"""
test_pipeline_v2.py - checks the simulator against the CS 5375 class notes.

Run:   python3 -m unittest -v test_pipeline_v2
"""
import random
import unittest

from pipeline_evaluator_v2 import (BranchPredictor, ForwardingWithReordering,
                                   InstructionSetsParser, PipelineProcessorWithForwarding,
                                   PipelineProcessorWithoutForwarding, ReorderingWithoutForwarding,
                                   SimpleMicroProcessor, execute, load_program, rearrange,
                                   time_pipeline)

P = InstructionSetsParser()


def run(model, source, branch="stall"):
    return model(P.parse(source), branch).run()


class TestLectureExamples(unittest.TestCase):
    """Every timing-diagram example from Topic 3, with the numbers from the notes."""

    CASES = [
        # (program, model, CC needed, penalty, CPI)
        ("ex1_six_loads", PipelineProcessorWithoutForwarding, 10, 0, 1.0),
        ("ex1_six_loads", PipelineProcessorWithForwarding, 10, 0, 1.0),
        ("ex2_add_sub_and_or", PipelineProcessorWithoutForwarding, 10, 2, 1.5),
        ("ex2_add_sub_and_or", PipelineProcessorWithForwarding, 8, 0, 1.0),
        ("ex3_lw_sub_addi_sw_ori", PipelineProcessorWithoutForwarding, 13, 4, 1.8),
        ("ex3_lw_sub_addi_sw_ori", ReorderingWithoutForwarding, 9, 0, 1.0),
        ("ex3_lw_sub_addi_sw_ori", PipelineProcessorWithForwarding, 10, 1, 1.2),
        ("ex4_add_lw_sw", PipelineProcessorWithoutForwarding, 11, 4, 7 / 3),
        ("ex4_add_lw_sw", PipelineProcessorWithForwarding, 7, 0, 1.0),
    ]

    def test_cc_penalty_cpi(self):
        for name, model, cc, pen, cpi in self.CASES:
            with self.subTest(program=name, model=model.name):
                r = model(load_program(name)).run()
                self.assertEqual(r.cc, cc)
                self.assertEqual(r.penalty, pen)
                self.assertAlmostEqual(r.cpi, cpi, places=6)

    def test_rearranged_order_matches_notes(self):
        m = ReorderingWithoutForwarding(load_program("ex3_lw_sub_addi_sw_ori"))
        self.assertEqual([i.op for i in m.program.instructions], ["lw", "addi", "ori", "sub", "sw"])

    def test_forwarding_paths_match_notes(self):
        r = PipelineProcessorWithForwarding(load_program("ex2_add_sub_and_or")).run()
        self.assertEqual([t.forwards for t in r.timings], [[], [(1, "B")], [(1, "A")], []])
        r = PipelineProcessorWithForwarding(load_program("ex3_lw_sub_addi_sw_ori")).run()
        self.assertEqual(r.timings[1].forwards, [(1, "A")])      # lw x1 -> sub, after 1 stall
        self.assertEqual(r.timings[3].forwards, [(6, "C")])      # addi x6 -> sw x6
        r = PipelineProcessorWithForwarding(load_program("ex4_add_lw_sw")).run()
        self.assertEqual(r.timings[1].forwards, [(1, "B")])
        self.assertEqual(r.timings[2].forwards, [(1, "A"), (4, "C")])


class TestDataHazardRules(unittest.TestCase):
    def test_no_forwarding_distance_1_2_3(self):
        self.assertEqual(run(PipelineProcessorWithoutForwarding,
                             "add x1,x2,x3\nadd x4,x1,x5").penalty, 2)
        self.assertEqual(run(PipelineProcessorWithoutForwarding,
                             "add x1,x2,x3\nadd x9,x8,x7\nadd x4,x1,x5").penalty, 1)
        self.assertEqual(run(PipelineProcessorWithoutForwarding,
                             "add x1,x2,x3\nadd x9,x8,x7\nadd x6,x8,x7\nadd x4,x1,x5").penalty, 0)

    def test_alu_and_load_same_without_forwarding(self):
        a = run(PipelineProcessorWithoutForwarding, "add x1,x2,x3\nsub x4,x1,x5")
        b = run(PipelineProcessorWithoutForwarding, "lw x1,0(x2)\nsub x4,x1,x5")
        self.assertEqual(a.penalty, b.penalty)

    def test_earlier_stalls_count_toward_distance(self):
        # lw x1 ; add uses x1 (2 stalls) ; add uses x1 again -> no extra stall
        r = run(PipelineProcessorWithoutForwarding, "lw x1,0(x2)\nadd x4,x1,x5\nadd x5,x1,x2")
        self.assertEqual(r.penalty, 2)
        # chain of three dependent adds: 2 + 2
        r = run(PipelineProcessorWithoutForwarding, "add x1,x2,x3\nadd x4,x1,x5\nadd x2,x4,x5")
        self.assertEqual(r.penalty, 4)

    def test_forwarding_load_use_is_one_cc(self):
        self.assertEqual(run(PipelineProcessorWithForwarding, "lw x1,0(x2)\nsub x4,x1,x5").penalty, 1)
        self.assertEqual(run(PipelineProcessorWithForwarding, "add x1,x2,x3\nsub x4,x1,x5").penalty, 0)

    def test_load_then_store_data_uses_path_c(self):
        r = run(PipelineProcessorWithForwarding, "lw x4,0(x1)\nsw x4,12(x2)")
        self.assertEqual(r.penalty, 0)
        self.assertEqual(r.timings[1].forwards, [(4, "C")])
        # ...but a load feeding the store's BASE register still costs 1 CC
        self.assertEqual(run(PipelineProcessorWithForwarding, "lw x4,0(x1)\nsw x2,0(x4)").penalty, 1)

    def test_x0_never_creates_a_dependency(self):
        r = run(PipelineProcessorWithoutForwarding, "addi x0, x1, 5\nadd x2, x0, x0")
        self.assertEqual(r.penalty, 0)

    def test_lw_reads_only_its_base_register(self):
        r = run(PipelineProcessorWithoutForwarding, "add x3,x1,x2\nlw x4,0(x5)")
        self.assertEqual(r.penalty, 0)

    def test_cpi_formula(self):
        r = run(PipelineProcessorWithForwarding, "add x1,x2,x3\nadd x4,x5,x6")
        self.assertEqual(r.cc, 6)
        self.assertAlmostEqual(r.cpi, (6 - 4) / 2)

    def test_ideal_speedup_is_clock_ratio(self):
        prog = P.parse("\n".join(f"addi x{5 + i}, x0, {i}" for i in range(8)))
        s = SimpleMicroProcessor(prog).run().exec_time_ns
        p = PipelineProcessorWithForwarding(prog).run().exec_time_ns
        self.assertAlmostEqual(s / p, 2.0 / 0.6)


class TestRearranging(unittest.TestCase):
    def test_random_programs_keep_their_results(self):
        rng = random.Random(1)
        for _ in range(3000):
            prog = P.generate_random_program(rng.choice([5, 10, 20]), rng.random(), rng=rng)
            ref = execute(prog).state()
            for fw in (False, True):
                self.assertEqual(execute(rearrange(prog, fw)).state(), ref)

    def test_rearranging_never_slower(self):
        rng = random.Random(2)
        for _ in range(1000):
            prog = P.generate_random_program(10, rng.random(), rng=rng)
            self.assertLessEqual(ReorderingWithoutForwarding(prog).run().cc,
                                 PipelineProcessorWithoutForwarding(prog).run().cc)
            self.assertLessEqual(ForwardingWithReordering(prog).run().cc,
                                 PipelineProcessorWithForwarding(prog).run().cc)

    def test_loop_programs_keep_their_results(self):
        for name in ("for_sum", "array_sum", "while_loop", "nested_loop", "bubble_sort"):
            prog = load_program(name)
            ref = execute(prog).state()
            for fw in (False, True):
                with self.subTest(program=name, forwarding=fw):
                    self.assertEqual(execute(rearrange(prog, fw)).state(), ref)


class TestBranches(unittest.TestCase):
    TAKEN = "beq x0, x0, L\naddi x5, x0, 1\nL: addi x6, x0, 2"
    NOT_TAKEN = "bne x0, x0, L\naddi x5, x0, 1\nL: addi x6, x0, 2"

    def test_stall_costs_2cc(self):
        self.assertEqual(run(PipelineProcessorWithForwarding, self.TAKEN, "stall").penalty, 2)
        self.assertEqual(run(PipelineProcessorWithForwarding, self.NOT_TAKEN, "stall").penalty, 2)

    def test_static_prediction(self):
        self.assertEqual(run(PipelineProcessorWithForwarding, self.TAKEN, "not_taken").penalty, 2)
        self.assertEqual(run(PipelineProcessorWithForwarding, self.NOT_TAKEN, "not_taken").penalty, 0)
        self.assertEqual(run(PipelineProcessorWithForwarding, self.TAKEN, "taken").penalty, 0)
        self.assertEqual(run(PipelineProcessorWithForwarding, self.NOT_TAKEN, "taken").penalty, 2)

    def test_one_bit_state_machine(self):
        bp = BranchPredictor("1bit")
        seq = []
        for outcome in (True, True, False, True):
            seq.append(bp.predict(0))
            bp.update(0, outcome)
        self.assertEqual(seq, [False, True, True, False])

    def test_two_bit_state_machine_from_notes(self):
        expected = {(3, True): 3, (3, False): 2, (2, True): 3, (2, False): 0,
                    (1, True): 3, (1, False): 0, (0, True): 1, (0, False): 0}
        for (state, taken), nxt in expected.items():
            bp = BranchPredictor("2bit")
            bp.table[0] = state
            self.assertEqual(bp.predict(0), state >= 2)
            bp.update(0, taken)
            self.assertEqual(bp.table[0], nxt)

    def test_two_bit_beats_one_bit_on_nested_loop(self):
        prog = load_program("nested_loop")
        one = PipelineProcessorWithForwarding(prog, "1bit").run()
        two = PipelineProcessorWithForwarding(prog, "2bit").run()
        self.assertLess(two.mispredictions, one.mispredictions)


class TestLoopPrograms(unittest.TestCase):
    def test_results(self):
        self.assertEqual(execute(load_program("for_sum")).regs[8], 45)          # s0
        self.assertEqual(execute(load_program("while_loop")).regs[9], 15)       # s1 = i
        e = execute(load_program("nested_loop"))
        self.assertEqual(e.mem[0x3000 + 256], sum(range(1, 65)))
        prog = load_program("array_sum")
        e = execute(prog)
        self.assertEqual(e.mem[0x1000 + 80], sum(prog.init_mem[0x1000 + 4 * i] for i in range(20)))

    def test_bubble_sort_sorts(self):
        prog = load_program("bubble_sort")
        e = execute(prog)
        values = [e.mem[0x4000 + 4 * i] for i in range(12)]
        self.assertEqual(values, sorted(prog.init_mem[0x4000 + 4 * i] for i in range(12)))

    def test_penalty_accounting(self):
        for name in ("for_sum", "bubble_sort"):
            for fw in (False, True):
                for pol in ("stall", "not_taken", "taken", "1bit", "2bit"):
                    r = time_pipeline(load_program(name), fw, pol)
                    self.assertEqual(r.cc, r.ic + 4 + r.data_penalty + r.branch_penalty)


if __name__ == "__main__":
    unittest.main()
