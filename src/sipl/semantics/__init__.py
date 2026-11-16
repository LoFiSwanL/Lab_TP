"""Apply the AF rules to semantic terms without interpreting AST statements."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..ast import Program
from ..interpreter import DEFAULT_MAX_STEPS
from ..interpreter.model import PRIMITIVES, RunResult, State, _Execution, _nesting_limit
from ..model import SIPLError, SourceSpan
from .term import (
    Assign, Compose, Constant, Dereference, Expression, Identity, Iterate, Select, StateTerm,
    Superposition, build_term, format_term,
)

__all__ = ["ProofStep", "StateTerm", "build_term", "evaluate", "format_term"]


@dataclass(frozen=True, slots=True)
class ProofStep:
    rule: str
    phase: str
    span: SourceSpan
    state: State
    value: int | bool | None = None
    subject: str | None = None
    iteration: int | None = None


ProofSink = Callable[[ProofStep], None]


class _Evaluator(_Execution):
    def __init__(self, initial, max_steps: int, on_step: ProofSink | None):
        super().__init__(initial, max_steps)
        self.on_step = on_step

    def record(self, rule: str, phase: str, span: SourceSpan, **detail) -> None:
        if self.on_step is not None:
            self.on_step(ProofStep(rule, phase, span, self.state.copy(), **detail))

    def expression(self, term: Expression) -> int | bool:
        match term:
            case Constant(number=number):
                return number
            case Dereference(name=name):
                self.record("AF_DNM", "lookup", term.span, subject=name)
                value = self.read(name, term.span)
                self.record("AF_DNM", "value", term.span, subject=name, value=value)
                return value
            case Superposition(function=function, operands=operands):
                self.record("AF_S", "apply", term.span, subject=function)
                # All operands are evaluated in the same state, including both operands of or.
                values = [self.expression(operand) for operand in operands]
                value = PRIMITIVES[function](*values)
                self.record("AF_S", "value", term.span, subject=function, value=value)
                return value
        raise TypeError(type(term).__name__)

    def guard(self, condition: Expression, rule: str, iteration: int | None = None) -> bool:
        self.tick(condition.span)
        holds = self.expression(condition)
        assert type(holds) is bool
        self.record(rule, "condition", condition.span, value=holds, iteration=iteration)
        return holds

    def apply(self, term: StateTerm) -> None:
        match term:
            case Assign(name=name, expression=expression):
                self.tick(term.span)
                self.record("AF_AS", "before", term.span, subject=name)
                value = self.expression(expression)
                assert type(value) is int
                self.state[name] = value
                self.record("AF_AS", "after", term.span, subject=name, value=value)
            case Compose(first=first, second=second):
                self.record("AF_SEQ", "before", term.span)
                self.apply(first)
                self.record("AF_SEQ", "between", term.span)
                self.apply(second)
                self.record("AF_SEQ", "after", term.span)
            case Select(condition=condition, when_true=yes, when_false=no):
                self.record("AF_IF", "before", term.span)
                self.apply(yes if self.guard(condition, "AF_IF") else no)
                self.record("AF_IF", "after", term.span)
            case Iterate(condition=condition, body=body):
                iteration = 0
                self.record("AF_WH", "before", term.span, iteration=iteration)
                while self.guard(condition, "AF_WH", iteration):
                    self.apply(body)
                    iteration += 1
                    self.record("AF_WH", "after_iteration", term.span, iteration=iteration)
            case Identity():
                self.tick(term.span)
                self.record("AF_ID", "same_state", term.span)
            case _:
                raise TypeError(type(term).__name__)


def evaluate(
    term: StateTerm | Program,
    initial: Mapping[str, int] | None = None,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    on_step: ProofSink | None = None,
) -> RunResult:
    execution = _Evaluator(initial, max_steps, on_step)
    try:
        if isinstance(term, Program):
            term = build_term(term)
        execution.apply(term)
        return execution.completed()
    except SIPLError as error:
        return execution.stopped(error.diagnostic)
    except RecursionError:
        return execution.stopped(_nesting_limit(term.span))
