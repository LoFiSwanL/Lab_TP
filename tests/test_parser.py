import sys
import unittest

from sipl import ast, parse
from sipl.model import Position, SIPLError

VALID = (
    "begin skip end",
    "begin X := 0 end",
    "begin X := -21 end",
    "begin X := Y + 1 end",
    "begin X := (X + 2) * 3 end",
    "begin X := 8-3-2 end",
    "begin X := 1--2 end",
    "begin X := 1; Y := X; skip end",
    "begin begin skip; skip end end",
    "begin if X = 0 then skip else X := 1 end",
    "begin while Y > 0 do Y := Y - 1 end",
    "begin if ¬(X = 0 ∨ Y > 1) then skip else skip end",
    "begin if (X + 2) * (-1) > -2 then skip else skip end",
    "begin if ((X+2)=3) then skip else skip end",
    "begin while X > 0 do if Y = 1 then skip else X := 0 end",
    "begin beginning := 1; end1 := beginning end",
)
INVALID = (
    "",
    "skip",
    "begin end",
    "begin skip",
    "begin skip; end",
    "begin X = 1 end",
    "begin X := -Y end",
    "begin X := +1 end",
    "begin X := - 1 end",
    "begin X := 2 / 1 end",
    "begin X := Y mod 2 end",
    "begin if X = 1 then skip end",
    "begin if X > 1 > 0 then skip else skip end",
    "begin while X < 1 do skip end",
    "begin while X > 1 skip end",
    "beginX := 1 end",
    "begin X := 1end",
    "begin skip := 0 end",
    "begin skip end skip",
    "begin X := (1 + 2 end",
    "begin 1X := 2 end",
)


class ParserTests(unittest.TestCase):
    def test_valid_programs(self):
        for source in VALID:
            with self.subTest(source=source):
                self.assertIsInstance(parse(source), ast.Program)

    def test_invalid_programs(self):
        for source in INVALID:
            with self.subTest(source=source), self.assertRaises(SIPLError) as context:
                parse(source)
            self.assertEqual(context.exception.diagnostic.code, "syntax_error")
            self.assertIsNotNone(context.exception.diagnostic.span)
            self.assertTrue(context.exception.diagnostic.expected)

    def test_labeled_ast_and_span(self):
        source = "  begin\r\n    XA := (1 + 2) * 3\r\n  end\r\n"
        program = parse(source)
        self.assertEqual(program.span.start, Position(2, 1, 3))
        self.assertEqual(program.span.end.offset, source.index("end") + 3)
        assignment = program.body
        self.assertIsInstance(assignment, ast.Assignment)
        self.assertEqual(assignment.target.span.start, Position(source.index("XA"), 2, 5))
        self.assertEqual(assignment.target.span.end.column, 7)
        self.assertIsInstance(assignment.expression.left, ast.ArithmeticGroup)
        self.assertEqual(assignment.expression.op, "*")
        group = assignment.expression.left
        self.assertEqual(source[group.span.start.offset:group.span.end.offset], "(1 + 2)")
        self.assertEqual(group.expression.op, "+")

    def test_error_positions(self):
        for source, line, col, length in [
            ("begin\nA := @\nend", 2, 6, 1),
            ("begin skip\n", 2, 1, 0),
            ("begin X := 1; end", 1, 15, 3),
        ]:
            with self.subTest(source=source), self.assertRaises(SIPLError) as cm:
                parse(source)
            span = cm.exception.diagnostic.span
            self.assertEqual((span.start.line, span.start.column), (line, col))
            self.assertEqual(span.end.offset - span.start.offset, length)

    def test_literal_exceeding_python_conversion_limit(self):
        limit = sys.get_int_max_str_digits()
        if not limit:
            self.skipTest("Python має вимкнений ліміт цілих чисел")
        with self.assertRaises(SIPLError) as cm:
            parse(f"begin X := {'1' * (limit + 1)} end")
        self.assertEqual(cm.exception.diagnostic.code, "integer_limit")
        self.assertEqual(cm.exception.diagnostic.span.start.column, 12)
