"""The abstract syntax of P, S, a and b from the course grammar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .model import SourceSpan

ArithmeticOp = Literal["+", "-", "*"]
CompareOp = Literal["=", ">"]


@dataclass(frozen=True, slots=True)
class Node:
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Integer(Node):
    value: int


@dataclass(frozen=True, slots=True)
class Variable(Node):
    name: str


@dataclass(frozen=True, slots=True)
class ArithmeticBinary(Node):
    op: ArithmeticOp
    left: Arithmetic
    right: Arithmetic


@dataclass(frozen=True, slots=True)
class ArithmeticGroup(Node):
    expression: Arithmetic


Arithmetic = Integer | Variable | ArithmeticBinary | ArithmeticGroup


@dataclass(frozen=True, slots=True)
class Comparison(Node):
    op: CompareOp
    left: Arithmetic
    right: Arithmetic


@dataclass(frozen=True, slots=True)
class Disjunction(Node):
    left: Condition
    right: Condition


@dataclass(frozen=True, slots=True)
class Negation(Node):
    operand: Condition


@dataclass(frozen=True, slots=True)
class BooleanGroup(Node):
    condition: Condition


Condition = Comparison | Disjunction | Negation | BooleanGroup


@dataclass(frozen=True, slots=True)
class Assignment(Node):
    target: Variable
    expression: Arithmetic


@dataclass(frozen=True, slots=True)
class Sequence(Node):
    first: Statement
    second: Statement


@dataclass(frozen=True, slots=True)
class If(Node):
    condition: Condition
    then_branch: Statement
    else_branch: Statement


@dataclass(frozen=True, slots=True)
class While(Node):
    condition: Condition
    body: Statement


@dataclass(frozen=True, slots=True)
class Block(Node):
    body: Statement


@dataclass(frozen=True, slots=True)
class Skip(Node):
    pass


Statement = Assignment | Sequence | If | While | Block | Skip


@dataclass(frozen=True, slots=True)
class Program(Node):
    body: Statement
