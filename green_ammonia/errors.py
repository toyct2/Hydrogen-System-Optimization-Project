from __future__ import annotations

from dataclasses import dataclass


# dataclass가 reason을 받는 __init__을 만들고, __str__이 표시할 문구를 정한다.
# frozen=True는 생성 후 필드 변경을 막고, slots=True는 필드를 슬롯으로 관리한다.
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
