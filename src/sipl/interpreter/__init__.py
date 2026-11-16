"""Run the AST and optionally emit events as statements execute."""

from collections.abc import Callable, Mapping

from .. import ast
from ..model import SIPLError, SourceSpan
from .model import (
    ARITHMETIC, COMPARISON, EventKind, ExecutionEvent, RunResult, State,
    _Execution, _nesting_limit,
)

EventSink = Callable[[ExecutionEvent], None]
DEFAULT_MAX_STEPS = 10_000


class _Interpreter(_Execution):
    def __init__(self, initial, max_steps: int, on_event: EventSink | None):
        super().__init__(initial, max_steps)
        self.on_event = on_event

    def emit(self, kind: EventKind, span: SourceSpan, **detail) -> None:
        if self.on_event is not None:
            self.on_event(ExecutionEvent(kind, self.steps, span, self.state.copy(), **detail))

    def arithmetic(self, node: ast.Arithmetic) -> int:
        match node:
            case ast.Integer(value=value):
                return value
            case ast.Variable(name=name):
                return self.read(name, node.span)
            case ast.ArithmeticBinary(op=op, left=left, right=right):
                return ARITHMETIC[op](self.arithmetic(left), self.arithmetic(right))
            case ast.ArithmeticGroup(expression=expression):
                return self.arithmetic(expression)
        raise TypeError(type(node).__name__)

    def condition(self, node: ast.Condition) -> bool:
        match node:
            case ast.Comparison(op=op, left=left, right=right):
                return COMPARISON[op](self.arithmetic(left), self.arithmetic(right))
            case ast.Disjunction(left=left, right=right):
                left_value = self.condition(left)
                right_value = self.condition(right)
                return left_value or right_value
            case ast.Negation(operand=operand):
                return not self.condition(operand)
            case ast.BooleanGroup(condition=condition):
                return self.condition(condition)
        raise TypeError(type(node).__name__)

    def guard(self, node: ast.Condition, statement: str) -> bool:
        self.tick(node.span)
        holds = self.condition(node)
        self.emit("ConditionChecked", node.span, statement=statement, condition=holds)
        return holds

    def statement(self, node: ast.Statement) -> None:
        name = type(node).__name__
        self.emit("BeforeStatement", node.span, statement=name)
        match node:
            case ast.Assignment(target=target, expression=expression):
                self.tick(node.span)
                value = self.arithmetic(expression)
                old_value = self.state.get(target.name)
                self.state[target.name] = value
                if old_value != value:
                    self.emit(
                        "VariableChanged", target.span, statement=name, variable=target.name,
                        old_value=old_value, new_value=value,
                    )
            case ast.Sequence(first=first, second=second):
                self.statement(first)
                self.statement(second)
            case ast.If(condition=condition, then_branch=yes, else_branch=no):
                self.statement(yes if self.guard(condition, name) else no)
            case ast.While(condition=condition, body=body):
                while self.guard(condition, name):
                    self.statement(body)
            case ast.Block(body=body):
                self.statement(body)
            case ast.Skip():
                self.tick(node.span)
            case _:
                raise TypeError(name)
        self.emit("AfterStatement", node.span, statement=name)


def run(
    program: ast.Program,
    initial: Mapping[str, int] | None = None,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    on_event: EventSink | None = None,
) -> RunResult:
    execution = _Interpreter(initial, max_steps, on_event)
    try:
        execution.statement(program.body)
        result = execution.completed()
    except SIPLError as error:
        result = execution.stopped(error.diagnostic)
    except RecursionError:
        result = execution.stopped(_nesting_limit(program.span))
    execution.emit("ExecutionFinished", program.span, status=result.status)
    return result
