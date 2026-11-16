from pathlib import Path
import unittest

from sipl import build_term, evaluate, format_term, parse, run

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return parse((ROOT / "examples" / f"{name}.sipl").read_text(encoding="utf-8"))


class ExecutionTests(unittest.TestCase):
    def assert_evaluations(self, program, initial, expected, steps):
        direct = run(program, initial)
        self.assertEqual(direct.status, "completed")
        self.assertEqual(direct.final_state, expected)
        self.assertEqual(direct.steps, steps)
        self.assertEqual(evaluate(build_term(program), initial), direct)

    def test_power_practicum(self):
        p = example("power")
        self.assert_evaluations(p, {"X": 5, "Y": 2}, {"X": 5, "Y": 0, "R": 25}, 8)
        self.assert_evaluations(p, {"X": -2, "Y": 0}, {"X": -2, "Y": 0, "R": 1}, 2)

    def test_gcd_nikitchenko_both_branches(self):
        p = example("gcd")
        self.assert_evaluations(p, {"M": 8, "N": 16}, {"M": 8, "N": 8}, 4)
        self.assert_evaluations(p, {"M": 18, "N": 12}, {"M": 6, "N": 6}, 7)

    def test_boolean_operators_parentheses_and_skip(self):
        p = example("condition")
        self.assert_evaluations(p, {"X": 5, "Y": 7}, {"X": 5, "Y": 7, "S": -1}, 3)
        self.assert_evaluations(p, {"X": 1, "Y": 0}, {"X": 1, "Y": 0, "R": 4, "S": -1}, 3)
        self.assert_evaluations(p, {"X": -2, "Y": 1}, {"X": -2, "Y": 1, "R": -2, "S": -1}, 3)

    def test_precedence(self):
        src = ("begin R := 2+3*4; A := 8-3-2; B := 1--2; "
               "if ¬R = 14 ∨ B = 3 then K := 1 else K := 2 end")
        self.assert_evaluations(parse(src), {}, {"R": 14, "A": 3, "B": 3, "K": 1}, 5)

    def test_sequence_is_outside_while_and_if(self):
        src = ("begin K:=2; while K>0 do K:=K-1; "
               "if K=1 then R:=1 else R:=2; R:=R+1 end")
        self.assert_evaluations(parse(src), {}, {"K": 0, "R": 3}, 9)

    def test_inactive_if_branch_and_false_loop_are_not_evaluated(self):
        p = parse("begin if 1 = 1 then X := 2 else X := U; while 0 > 1 do X := U end")
        self.assert_evaluations(p, {}, {"X": 2}, 3)

    def test_missing_name_no_final_state_and_source_span(self):
        p = parse("begin\n  X := 1;\n  Y := Z + 2\nend")
        events, proof = [], []
        direct = run(p, on_event=events.append)
        self.assertEqual(direct.status, "undefined")
        self.assertEqual(direct.steps, 2)
        self.assertIsNone(direct.final_state)
        self.assertEqual(direct.diagnostic.code, "undefined_variable")
        start = direct.diagnostic.span.start
        self.assertEqual((start.line, start.column), (3, 8))
        self.assertEqual(events[-1].state, {"X": 1})
        self.assertEqual(events[-1].status, "undefined")
        self.assertEqual(evaluate(p, on_step=proof.append), direct)
        self.assertEqual((proof[-1].rule, proof[-1].phase, proof[-1].subject), ("AF_DNM", "lookup", "Z"))

    def test_disjunction_is_strict_superposition(self):
        p = parse("begin if 1 = 1 ∨ U = 1 then skip else skip end")
        direct = run(p)
        self.assertEqual(direct.status, "undefined")
        self.assertEqual(evaluate(p), direct)

    def test_limit_is_distinct_from_undefined(self):
        p = parse("begin while 1 = 1 do skip end")
        events = []
        direct = run(p, max_steps=5, on_event=events.append)
        self.assertEqual((direct.status, direct.steps, direct.final_state), ("limit", 5, None))
        self.assertEqual(direct.diagnostic.code, "step_limit")
        self.assertEqual(events[-1].status, "limit")
        self.assertEqual(evaluate(p, max_steps=5), direct)
        self.assertEqual(run(p, max_steps=0).steps, 0)
        skip = parse("begin skip end")
        self.assertEqual(run(skip, max_steps=1).status, "completed")

    def test_api_rejects_invalid_limits_and_state(self):
        p = parse("begin skip end")
        for f in (run, evaluate):
            with self.assertRaises(ValueError):
                f(p, max_steps=-1)
            with self.assertRaises(ValueError):
                f(p, {"X": True})

    def test_event_order_and_state_snapshots(self):
        initial = {"X": 2}
        events = []
        p = parse("begin if X > 0 then X := X-1 else skip end")
        result = run(p, initial, on_event=events.append)
        self.assertEqual(initial, {"X": 2})
        self.assertEqual(result.final_state, {"X": 1})
        self.assertEqual([e.kind for e in events], [
            "BeforeStatement", "ConditionChecked", "BeforeStatement", "VariableChanged",
            "AfterStatement", "AfterStatement", "ExecutionFinished",
        ])
        self.assertEqual((events[3].variable, events[3].old_value, events[3].new_value), ("X", 2, 1))
        self.assertEqual(events[0].state, {"X": 2})
        self.assertEqual(events[-1].state, {"X": 1})
        self.assertEqual(events[-1].status, "completed")
        events[0].state["X"] = 111
        self.assertEqual(events[1].state, {"X": 2})

    def test_unchanged_assignment_emits_no_variable_change(self):
        events = []
        run(parse("begin X := X end"), {"X": 3}, on_event=events.append)
        self.assertNotIn("VariableChanged", [e.kind for e in events])

    def test_practicum_proof_states_and_rule_order(self):
        proof = []
        evaluate(example("power"), {"X": 5, "Y": 2}, on_step=proof.append)
        iterations = [
            (s.iteration, s.state["R"], s.state["Y"])
            for s in proof if s.rule == "AF_WH" and s.phase == "after_iteration"
        ]
        self.assertEqual(iterations, [(1, 5, 1), (2, 25, 0)])
        self.assertEqual(
            [s.value for s in proof if s.rule == "AF_WH" and s.phase == "condition"],
            [True, True, False],
        )
        gcd = []
        evaluate(example("gcd"), {"M": 8, "N": 16}, on_step=gcd.append)
        self.assertEqual([s.value for s in gcd if s.rule == "AF_IF" and s.phase == "condition"], [False])
        self.assertEqual([s.subject for s in gcd if s.rule == "AF_AS" and s.phase == "after"], ["N"])


class GoldenTests(unittest.TestCase):
    def test_course_notation(self):
        for name in ("power", "gcd", "condition"):
            with self.subTest(name=name):
                expected = (ROOT / "tests" / "golden" / f"{name}.txt").read_text(encoding="utf-8").strip()
                self.assertEqual(format_term(build_term(example(name))), expected)

    def test_right_grouping_of_composition(self):
        p = parse("begin skip; begin skip; skip end end")
        self.assertEqual(format_term(build_term(p)), "id · (id · id)")
