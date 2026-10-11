from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InvalidModelInput(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class SolverFailure(Exception):
    termination_condition: str

    def __str__(self) -> str:
        return f"최적해 확인 실패: {self.termination_condition}"
