"""Lark grammar to our typed AST."""

from functools import lru_cache
from importlib.resources import files
import re

from lark import Lark, Token, Transformer_NonRecursive
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken, VisitError

from . import ast
from .model import Diagnostic, Position, SIPLError, SourceSpan

KEYWORDS = frozenset(("begin", "end", "if", "then", "else", "while", "do", "skip"))


def is_variable(name: str) -> bool:
    return name not in KEYWORDS and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name) is not None


@lru_cache(maxsize=1)
def _parser() -> Lark:
    source = files("sipl").joinpath("grammar", "sipl.lark").read_text(encoding="utf-8")
    return Lark(source, start="program", parser="lalr", lexer="contextual", propagate_positions=True)


def _span(meta) -> SourceSpan:
    return SourceSpan(
        Position(meta.start_pos, meta.line, meta.column),
        Position(meta.end_pos, meta.end_line, meta.end_column),
    )


class _ASTBuilder(Transformer_NonRecursive):
    def __default__(self, rule, children, meta):
        span = _span(meta)
        match rule:
            case "program":
                return ast.Program(span, children[0])
            case "assignment":
                token, expression = children
                return ast.Assignment(span, ast.Variable(_span(token), str(token)), expression)
            case "sequence":
                return ast.Sequence(span, *children)
            case "if_statement":
                return ast.If(span, *children)
            case "while_statement":
                return ast.While(span, *children)
            case "block":
                return ast.Block(span, children[0])
            case "skip":
                return ast.Skip(span)
            case "number":
                try:
                    return ast.Integer(span, int(children[0]))
                except ValueError:
                    raise SIPLError(Diagnostic(
                        "integer_limit", "Ціле число перевищує ліміт перетворення Python.", span
                    )) from None
            case "variable":
                return ast.Variable(span, str(children[0]))
            case "add":
                return ast.ArithmeticBinary(span, "+", *children)
            case "sub":
                return ast.ArithmeticBinary(span, "-", *children)
            case "mult":
                return ast.ArithmeticBinary(span, "*", *children)
            case "arithmetic_group":
                return ast.ArithmeticGroup(span, children[0])
            case "equal":
                return ast.Comparison(span, "=", *children)
            case "greater":
                return ast.Comparison(span, ">", *children)
            case "disjunction":
                return ast.Disjunction(span, *children)
            case "negation":
                return ast.Negation(span, children[0])
            case "boolean_group":
                return ast.BooleanGroup(span, children[0])
        raise AssertionError(f"Невідоме правило граматики: {rule}")


def _expected(parser: Lark, names: set[str]) -> tuple[str, ...]:
    labels = {"NAME": "ім'я змінної", "INTEGER": "ціле число", "$END": "кінець вводу"}
    for terminal in parser.terminals:
        if terminal.name.removeprefix("_").lower() in KEYWORDS:
            labels[terminal.name] = repr(terminal.name.removeprefix("_").lower())
        elif terminal.pattern.type == "str":
            labels[terminal.name] = repr(terminal.pattern.value)
    return tuple(sorted(labels.get(name, name) for name in names))


def _position(source: str, offset: int) -> Position:
    return Position(offset, source.count("\n", 0, offset) + 1, offset - source.rfind("\n", 0, offset))


def _diagnostic(error: UnexpectedInput, source: str, parser: Lark) -> Diagnostic:
    if isinstance(error, UnexpectedToken):
        token: Token = error.token
        if token.type == "$END":
            pos = _position(source, len(source))
            span = SourceSpan(pos, pos)
            message = "Неочікуваний кінець програми."
        else:
            span = _span(token)
            message = f"Неочікувана лексема {str(token)!r}."
        return Diagnostic("syntax_error", message, span, _expected(parser, error.expected))
    if isinstance(error, UnexpectedCharacters):
        offset = error.pos_in_stream
        span = SourceSpan(_position(source, offset), _position(source, offset + 1))
        return Diagnostic(
            "syntax_error", f"Неочікуваний символ {source[offset]!r}.", span,
            _expected(parser, error.allowed or set())
        )
    return Diagnostic("syntax_error", str(error))


def parse(source: str) -> ast.Program:
    """Read one complete SIPL program or raise SIPLError with a diagnostic."""
    parser = _parser()
    try:
        return _ASTBuilder().transform(parser.parse(source))
    except UnexpectedInput as error:
        raise SIPLError(_diagnostic(error, source, parser)) from None
    except VisitError as error:
        if isinstance(error.orig_exc, SIPLError):
            raise error.orig_exc from None
        raise
