"""Command-line client of the library. The versioned JSON contract is bundled."""

import argparse
from dataclasses import fields, is_dataclass
import json
import sys

from . import ast, build_term, evaluate, format_term, parse, run
from .interpreter import DEFAULT_MAX_STEPS
from .model import Diagnostic, SIPLError
from .parser import is_variable
from .semantics.term import Term

SCHEMA_VERSION = 1
EXIT_CODES = {"ok": 0, "completed": 0, "error": 2, "undefined": 3, "limit": 4}


def _json_value(value):
    if is_dataclass(value):
        payload = {f.name: _json_value(getattr(value, f.name)) for f in fields(value)}
        if isinstance(value, (ast.Node, Term)):
            payload["kind"] = type(value).__name__
        return payload
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _integer_limit(error: ValueError) -> bool:
    return "integer string conversion" in str(error)


def _load_state(text: str) -> dict[str, int]:
    def unique_object(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError(f"Ім'я {name!r} у стані задане двічі.")
            result[name] = value
        return result

    try:
        state = json.loads(text, object_pairs_hook=unique_object)
    except ValueError as error:
        message = "Початковий стан не є коректним JSON-об'єктом."
        if not isinstance(error, json.JSONDecodeError):
            message = str(error)
        raise SIPLError(Diagnostic("invalid_state", message)) from None
    if not isinstance(state, dict) or any(
        not is_variable(name) or type(value) is not int for name, value in state.items()
    ):
        raise SIPLError(Diagnostic(
            "invalid_state", "Стан має бути JSON-об'єктом з іменами SIPL і цілими числами."
        ))
    return state


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sipl", description="Інструменти базової мови SIPL")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, description in {
        "parse": "побудувати абстрактне синтаксичне дерево",
        "check": "перевірити синтаксис",
        "run": "виконати AST",
        "trace": "виконати AST і показати події",
        "term": "побудувати семантичний терм",
        "eval": "обчислити семантичний терм і показати правила AF",
    }.items():
        cmd = commands.add_parser(command, help=description, description=description)
        cmd.add_argument("file", help="UTF-8 файл SIPL або - для stdin")
        cmd.add_argument("--json", action="store_true", help="вивести результат у JSON v1")
        if command in ("run", "trace", "eval"):
            cmd.add_argument("--state", default="{}", help="початковий стан як JSON-об'єкт")
            cmd.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS, help="ліміт кроків")
    return parser.parse_args(argv)


def _read_source(file: str) -> str:
    try:
        if file == "-":
            return sys.stdin.read()
        with open(file, encoding="utf-8", newline="") as stream:
            return stream.read()
    except (OSError, UnicodeError) as error:
        raise SIPLError(Diagnostic("read_error", f"Не вдалося прочитати програму: {error}")) from None


def _execute(args: argparse.Namespace) -> tuple[str, dict, Diagnostic | None]:
    program = parse(_read_source(args.file))
    if args.command == "check":
        return "ok", {}, None
    if args.command == "parse":
        return "ok", {"ast": _json_value(program)}, None
    if args.command == "term":
        term = build_term(program)
        return "ok", {"term": _json_value(term), "notation": format_term(term)}, None
    if args.max_steps < 0:
        raise SIPLError(Diagnostic("invalid_limit", "Ліміт кроків має бути невід'ємним."))
    initial = _load_state(args.state)
    trace = []
    if args.command == "eval":
        result = evaluate(program, initial, max_steps=args.max_steps, on_step=trace.append)
    else:
        sink = trace.append if args.command == "trace" else None
        result = run(program, initial, max_steps=args.max_steps, on_event=sink)
    data = {"steps": result.steps, "final_state": result.final_state}
    if args.command == "trace":
        data["events"] = _json_value(trace)
    elif args.command == "eval":
        data["proof"] = _json_value(trace)
    return result.status, data, result.diagnostic


def _diagnostic_text(diagnostic: dict) -> str:
    span = diagnostic["span"]
    location = f'{span["start"]["line"]}:{span["start"]["column"]}: ' if span else ""
    expected = f' Очікувалось: {", ".join(diagnostic["expected"])}.' if diagnostic["expected"] else ""
    return location + diagnostic["message"] + expected


def _human(command: str, status: str, data: dict, diagnostic: dict | None) -> str:
    lines = []
    if command == "check" and status == "ok":
        return "Синтаксис коректний."
    if "ast" in data:
        return json.dumps(data["ast"], ensure_ascii=False, indent=2)
    if "notation" in data:
        return data["notation"]
    for event in data.get("events", []):
        start = event["span"]["start"]
        details = event["statement"] or event["status"] or ""
        if event["variable"] is not None:
            details += f' {event["variable"]}: {event["old_value"]} -> {event["new_value"]}'
        if event["condition"] is not None:
            details += f' {str(event["condition"]).lower()}'
        lines.append(
            f'{event["step"]:>3} {start["line"]}:{start["column"]} {event["kind"]} {details} {event["state"]}'
        )
    for step in data.get("proof", []):
        iteration = "" if step["iteration"] is None else f' ітерація={step["iteration"]}'
        details = "" if step["subject"] is None else f' {step["subject"]}'
        value = "" if step["value"] is None else f' => {step["value"]}'
        lines.append(f'{step["rule"]} {step["phase"]}{iteration}{details}{value} {step["state"]}')
    if "final_state" in data:
        if data["final_state"] is not None:
            lines.append(f'Кінцевий стан: {data["final_state"]}')
        else:
            lines.append("Кінцевий стан не отримано.")
    if diagnostic is not None:
        lines.append(_diagnostic_text(diagnostic))
    return "\n".join(lines)


def _response(args: argparse.Namespace, status: str, data: dict, diagnostic: Diagnostic | None) -> str:
    payload = _json_value(diagnostic)
    if args.json:
        return json.dumps({
            "schema_version": SCHEMA_VERSION,
            "command": args.command,
            "status": status,
            "result": data,
            "diagnostic": payload,
        }, ensure_ascii=False)
    return _human(args.command, status, data, payload)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    try:
        status, data, diagnostic = _execute(args)
        output = _response(args, status, data, diagnostic)
    except SIPLError as error:
        status = "error"
        output = _response(args, status, {}, error.diagnostic)
    except RecursionError:
        status = "limit"
        output = _response(
            args, status, {}, Diagnostic("nesting_limit", "Перевищено ліміт вкладеності.")
        )
    except ValueError as error:
        if not _integer_limit(error):
            raise
        status = "limit"
        output = _response(args, status, {}, Diagnostic(
            "integer_limit", "Число перевищує ліміт перетворення Python."
        ))
    print(output, file=sys.stderr if status == "error" and not args.json else sys.stdout)
    return EXIT_CODES[status]
