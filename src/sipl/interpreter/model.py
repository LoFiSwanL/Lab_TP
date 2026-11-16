"""Execution data shared by the interpreter and semantic evaluator."""

from dataclasses import dataclass
from operator import add, eq, gt, mul, not_, or_, sub
from typing import Literal

from ..model import Diagnostic, SIPLError, SourceSpan

State = dict[str, int]
Status = Literal["completed", "undefined", "limit"]
EventKind = Literal[
    "BeforeStatement", "AfterStatement", "VariableChanged", "ConditionChecked", "ExecutionFinished"
]

ARITHMETIC = {"+": add, "-": sub, "*": mul}
COMPARISON = {"=": eq, ">": gt}
PRIMITIVES = {
    "add": add, "sub": sub, "mult": mul, "eq": eq, "gr": gt, "or": or_, "neg": not_,
}


@dataclass(frozen=True, slots=True)
class RunResult:
    status: Status
    steps: int
    final_state: State | None
    diagnostic: Diagnostic | None = None


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    kind: EventKind
    step: int
    span: SourceSpan
    state: State
    statement: str | None = None
    variable: str | None = None
    old_value: int | None = None
    new_value: int | None = None
    condition: bool | None = None
    status: Status | None = None


class _Execution:
    def __init__(self, initial, max_steps: int):
        if type(max_steps) is not int or max_steps < 0:
            raise ValueError("max_steps має бути невід'ємним цілим числом.")
        if initial is not None and any(type(value) is not int for value in initial.values()):
            raise ValueError("Стан SIPL може містити лише цілі числа.")
        self.state: State = dict(initial) if initial is not None else {}
        self.max_steps = max_steps
        self.steps = 0

    def tick(self, span: SourceSpan) -> None:
        if self.steps >= self.max_steps:
            raise SIPLError(Diagnostic("step_limit", "Досягнуто ліміту кроків.", span))
        self.steps += 1

    def read(self, name: str, span: SourceSpan) -> int:
        if name not in self.state:
            raise SIPLError(Diagnostic("undefined_variable", f"Змінна {name!r} не має значення.", span))
        return self.state[name]

    def completed(self) -> RunResult:
        return RunResult("completed", self.steps, self.state.copy())

    def stopped(self, diagnostic: Diagnostic) -> RunResult:
        status = "undefined" if diagnostic.code == "undefined_variable" else "limit"
        return RunResult(status, self.steps, None, diagnostic)


def _nesting_limit(span: SourceSpan) -> Diagnostic:
    return Diagnostic("nesting_limit", "Перевищено ліміт вкладеності обчислення.", span)
