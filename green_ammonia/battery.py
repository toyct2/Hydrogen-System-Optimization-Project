from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import pyomo.environ as pyo


@dataclass(frozen=True, slots=True)
class PhysicalBatteryHour:
    charge_mw: float
    discharge_mw: float
    extra_curtail_mw: float


def physical_dispatch(charge_mw: float, discharge_mw: float, round_trip_efficiency: float) -> PhysicalBatteryHour:
    """동시 충·방전 LP 해를 같은 SOC 변화의 순수 운전으로 바꾼다.

    배터리 손실로 소모되던 잉여전력은 `extra_curtail_mw`로 이동한다.
    따라서 설비비·계통사용·시간별 전력수지·SOC는 그대로 유지된다.
    """
    if charge_mw >= discharge_mw / round_trip_efficiency:
        physical_charge = charge_mw - discharge_mw / round_trip_efficiency
        physical_discharge = 0.0
    else:
        physical_charge = 0.0
        physical_discharge = discharge_mw - round_trip_efficiency * charge_mw
    extra_curtail = (charge_mw - discharge_mw) - (physical_charge - physical_discharge)
    return PhysicalBatteryHour(physical_charge, physical_discharge, extra_curtail)


def add_battery(model: pyo.ConcreteModel, round_trip_efficiency: float) -> None:
    """왕복효율을 충전·방전 두 경로에 대칭 배분한다.

    SOC[t] = SOC[t-1] + sqrt(eta)*charge[t] - discharge[t]/sqrt(eta).
    왕복효율은 함수 인자로 받으며 실행 파일의 기본 설정은 90%다.
    """
    eta = sqrt(round_trip_efficiency)
    model.bess_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.bess_mwh = pyo.Var(domain=pyo.NonNegativeReals)
    model.bess_charge = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.bess_discharge = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.bess_soc = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.bess_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.bess_soc[t]
        == m.bess_soc[(t - 1) % len(m.T)]
        + eta * m.bess_charge[t]
        - m.bess_discharge[t] / eta,
    )
    model.bess_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.bess_soc[t] <= m.bess_mwh
    )
    model.charge_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.bess_charge[t] <= m.bess_mw
    )
    model.discharge_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.bess_discharge[t] <= m.bess_mw
    )
