"""Terms of the SIPL algebra and the NS translation from syntax."""

from __future__ import annotations

from dataclasses import dataclass

from .. import ast
from ..model import SourceSpan

_ARITHMETIC = {"+": "add", "-": "sub", "*": "mult"}
_COMPARISON = {"=": "eq", ">": "gr"}


@dataclass(frozen=True, slots=True)
class Term:
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Constant(Term):
    number: int


@dataclass(frozen=True, slots=True)
class Dereference(Term):
    name: str


@dataclass(frozen=True, slots=True)
class Superposition(Term):
    function: str
    operands: tuple[Expression, ...]


Expression = Constant | Dereference | Superposition


@dataclass(frozen=True, slots=True)
class Assign(Term):
    name: str
    expression: Expression


@dataclass(frozen=True, slots=True)
class Compose(Term):
    first: StateTerm
    second: StateTerm


@dataclass(frozen=True, slots=True)
class Select(Term):
    condition: Expression
    when_true: StateTerm
    when_false: StateTerm


@dataclass(frozen=True, slots=True)
class Iterate(Term):
    condition: Expression
    body: StateTerm


@dataclass(frozen=True, slots=True)
class Identity(Term):
    pass


StateTerm = Assign | Compose | Select | Iterate | Identity


def _expression(node: ast.Arithmetic | ast.Condition) -> Expression:
    match node:
        case ast.Integer(value=value):
            return Constant(node.span, value)
        case ast.Variable(name=name):
            return Dereference(node.span, name)
        case ast.ArithmeticBinary(op=op, left=left, right=right):
            return Superposition(node.span, _ARITHMETIC[op], (_expression(left), _expression(right)))
        case ast.Comparison(op=op, left=left, right=right):
            return Superposition(node.span, _COMPARISON[op], (_expression(left), _expression(right)))
        case ast.Disjunction(left=left, right=right):
            return Superposition(node.span, "or", (_expression(left), _expression(right)))
        case ast.Negation(operand=operand):
            return Superposition(node.span, "neg", (_expression(operand),))
        case ast.ArithmeticGroup(expression=inner) | ast.BooleanGroup(condition=inner):
            return _expression(inner)
    raise TypeError(type(node).__name__)


def _statement(node: ast.Statement) -> StateTerm:
    match node:
        case ast.Assignment(target=target, expression=value):
            return Assign(node.span, target.name, _expression(value))
        case ast.Sequence(first=first, second=second):
            return Compose(node.span, _statement(first), _statement(second))
        case ast.If(condition=condition, then_branch=yes, else_branch=no):
            return Select(node.span, _expression(condition), _statement(yes), _statement(no))
        case ast.While(condition=condition, body=body):
            return Iterate(node.span, _expression(condition), _statement(body))
        case ast.Block(body=body):
            return _statement(body)
        case ast.Skip():
            return Identity(node.span)
    raise TypeError(type(node).__name__)


def build_term(program: ast.Program) -> StateTerm:
    return _statement(program.body)


def format_term(term: StateTerm | Expression) -> str:
    match term:
        case Constant(number=number):
            return "".join(ch + "\u0304" if ch.isdecimal() else ch for ch in str(number))
        case Dereference(name=name):
            return f"{name}⇒"
        case Superposition(function=function, operands=operands):
            index = "¹" if len(operands) == 1 else "²"
            args = ", ".join(format_term(operand) for operand in operands)
            return f"S{index}({function}, {args})"
        case Assign(name=name, expression=expression):
            return f"AS^{name}({format_term(expression)})"
        case Compose(first=first, second=second):
            right = format_term(second)
            if isinstance(second, Compose):
                right = f"({right})"
            return f"{format_term(first)} · {right}"
        case Select(condition=condition, when_true=yes, when_false=no):
            return f"IF({format_term(condition)}, {format_term(yes)}, {format_term(no)})"
        case Iterate(condition=condition, body=body):
            return f"WH({format_term(condition)}, {format_term(body)})"
        case Identity():
            return "id"
    raise TypeError(type(term).__name__)
