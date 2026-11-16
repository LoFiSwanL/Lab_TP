from importlib import resources
import json
from pathlib import Path
import subprocess
import sys
import unittest

from sipl.cli import main

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, source=None, status=0):
    process = subprocess.run(
        [sys.executable, "-m", "sipl", *args], input=source,
        capture_output=True, encoding="utf-8", cwd=ROOT, timeout=15,
    )
    if process.returncode != status:
        raise AssertionError((process.returncode, process.stdout, process.stderr))
    if "--json" in args:
        if process.stderr:
            raise AssertionError(process.stderr)
        return json.loads(process.stdout)
    return process


class CLITests(unittest.TestCase):
    def test_parse_check_json_and_help(self):
        result = cli("parse", "-", "--json", source="begin X := 2 end")
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["command"], "parse")
        self.assertIsNone(result["diagnostic"])
        tree = result["result"]["ast"]
        self.assertEqual(tree["kind"], "Program")
        self.assertEqual(tree["body"]["target"]["name"], "X")
        self.assertEqual(tree["body"]["expression"]["value"], 2)
        self.assertEqual(cli("check", "-", "--json", source="begin skip end")["status"], "ok")
        self.assertIn("trace", cli("--help").stdout)

    def test_error_codes_and_locations(self):
        invalid = cli("check", "-", "--json", source="begin\nX := @\nend", status=2)
        self.assertEqual(invalid["status"], "error")
        self.assertEqual(invalid["diagnostic"]["span"]["start"], {"offset": 11, "line": 2, "column": 6})
        for state in ("{", '{"X":true}', '{"if":1}', '{"X":1,"X":2}', "[]"):
            with self.subTest(state=state):
                invalid = cli("run", "-", "--json", "--state", state, source="begin skip end", status=2)
                self.assertEqual(invalid["diagnostic"]["code"], "invalid_state")
        negative = cli("run", "-", "--json", "--max-steps", "-1", source="begin skip end", status=2)
        self.assertEqual(negative["diagnostic"]["code"], "invalid_limit")
        missing = cli("check", "dummy-missing.sipl", "--json", status=2)
        self.assertEqual(missing["diagnostic"]["code"], "read_error")
        failed = cli("check", "-", source="begin @ end", status=2)
        self.assertIn("1:7", failed.stderr)
        self.assertFalse(failed.stdout)

    def test_run_trace_and_semantic_layer(self):
        source = "begin X := 1; if X > 0 then X := X+2 else skip end"
        for cmd in ("run", "trace", "eval"):
            with self.subTest(cmd=cmd):
                data = cli(cmd, "-", "--json", source=source)
                self.assertEqual(data["status"], "completed")
                self.assertEqual(data["result"]["steps"], 3)
                self.assertEqual(data["result"]["final_state"], {"X": 3})
                if cmd == "trace":
                    self.assertEqual(data["result"]["events"][-1]["kind"], "ExecutionFinished")
                if cmd == "eval":
                    self.assertIn("AF_IF", [p["rule"] for p in data["result"]["proof"]])
        data = cli("term", "-", "--json", source=source)
        self.assertEqual(data["result"]["term"]["kind"], "Compose")
        self.assertIn("IF(S²(gr, X⇒", data["result"]["notation"])

    def test_undefined_and_limit(self):
        undefined = cli("eval", "-", "--json", source="begin X := Z end", status=3)
        self.assertEqual(undefined["status"], "undefined")
        self.assertIsNone(undefined["result"]["final_state"])
        self.assertEqual(undefined["result"]["proof"][-1]["subject"], "Z")
        limited = cli(
            "trace", "-", "--json", "--max-steps", "4",
            source="begin while 1 = 1 do skip end", status=4,
        )
        self.assertEqual(limited["status"], "limit")
        self.assertIsNone(limited["result"]["final_state"])
        self.assertEqual(limited["result"]["events"][-1]["status"], "limit")

    def test_json_schema_is_packaged(self):
        schema = json.loads(resources.files("sipl").joinpath("result-v1.schema.json").read_text())
        self.assertIn("oneOf", schema)
        self.assertIn("ast", schema["$defs"])

    def test_in_process_entrypoint(self):
        # These paths also cover the human-readable CLI without mocking the interpreter.
        import contextlib
        from io import StringIO
        from unittest.mock import patch

        for cmd, source, code, fragment in [
            ("check", "begin skip end", 0, "Синтаксис коректний"),
            ("check", "begin @ end", 2, "1:7"),
            ("parse", "begin skip end", 0, '"kind": "Skip"'),
            ("term", "begin skip end", 0, "id"),
            ("run", "begin skip end", 0, "Кінцевий стан: {}"),
            ("trace", "begin if 1=1 then X:=2 else skip end", 0, "VariableChanged"),
            ("eval", "begin while 0>1 do skip end", 0, "ітерація=0"),
            ("run", "begin X := Z end", 3, "Кінцевий стан не отримано"),
        ]:
            with self.subTest(cmd=cmd, source=source):
                output = StringIO()
                with (
                    patch("sys.stdin", StringIO(source)),
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(output),
                ):
                    self.assertEqual(main([cmd, "-"]), code)
                self.assertIn(fragment, output.getvalue())
