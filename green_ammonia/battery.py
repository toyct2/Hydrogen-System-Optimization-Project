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
    # LP에는 충전과 방전을 동시에 막는 이진변수가 없다. 이 함수는 저장할
    # 시간별 결과만 순수 충전 또는 방전으로 환산한다. 논문 Eq. (19)의 일부가
    # 아니라 본 구현의 출력 후처리이며 최적화 변수·목적값은 바꾸지 않는다.
    # 임계값 discharge/eta는 두 흐름이 만드는 SOC 변화가 0인 지점이다.
    if charge_mw >= discharge_mw / round_trip_efficiency:
        physical_charge = charge_mw - discharge_mw / round_trip_efficiency
        physical_discharge = 0.0
    else:
        physical_charge = 0.0
        physical_discharge = discharge_mw - round_trip_efficiency * charge_mw
    # 제거한 동시 충방전의 순 전력소비는 출력제한으로 옮겨 전력수지를 보존한다.
    extra_curtail = (charge_mw - discharge_mw) - (physical_charge - physical_discharge)
    return PhysicalBatteryHour(physical_charge, physical_discharge, extra_curtail)


def add_battery(model: pyo.ConcreteModel, round_trip_efficiency: float) -> None:
    """왕복효율을 충전·방전 두 경로에 대칭 배분한다.

    SOC[t] = SOC[t-1] + sqrt(eta)*charge[t] - discharge[t]/sqrt(eta).
    왕복효율은 함수 인자로 받으며 실행 파일의 기본 설정은 90%다.
    """
    # 논문 Eq. (19)는 방전측에 손실을 둔다. 이 코드는 왕복효율 eta_RT를
    # sqrt(eta_RT) 충전효율과 sqrt(eta_RT) 방전효율로 대칭 분배한다.
    # 따라서 식 모양과 손실 배치는 논문 Eq. (19)와 동일하지 않다.
    eta = sqrt(round_trip_efficiency)
    model.bess_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.bess_mwh = pyo.Var(domain=pyo.NonNegativeReals)
    model.bess_charge = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.bess_discharge = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.bess_soc = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    # SOC[t] = SOC[t-1] + sqrt(eta_RT) × charge[t]
    #          - discharge[t] / sqrt(eta_RT), 1시간 간격이므로 MW·h = MWh.
    # (t - 1) % len(T)는 논문 Sec. 3.4의 연간 순환 저장 조건에 대응한다.
    model.bess_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.bess_soc[t]
        == m.bess_soc[(t - 1) % len(m.T)]
        + eta * m.bess_charge[t]
        - m.bess_discharge[t] / eta,
    )
    # 논문 Eq. (4)는 BESS 충전·방전 전력용량을 제한한다.
    # 저장 에너지용량은 Sec. 3.4의 최대 재고 정의에 대응한다.
    model.bess_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.bess_soc[t] <= m.bess_mwh
    )
    model.charge_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.bess_charge[t] <= m.bess_mw
    )
    model.discharge_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.bess_discharge[t] <= m.bess_mw
    )
