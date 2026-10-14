from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import (
    ALK_MWH_PER_T_H2,
    H2_COMP_MWH_PER_T_H2,
    H2_T_PER_NH3_T,
    RO_MWH_PER_T_H2,
    ModelSettings,
)

def add_hydrogen_system(model: pyo.ConcreteModel, settings: ModelSettings) -> None:
    """논문 Eq. (9), (16), (20)을 1시간 시간축에 추가한다.

    `alk_power[t]`는 MWh/h=MW이고 `h2_production[t]`는 t/h다.
    전해조는 모든 최적화 단계에서 Eq. (9)의 정효율을 사용한다.
    시간별 생산량에서 HB의 반응식상 수소 소비를 뺀 값이 재고 변화다.
    """
    model.alk_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.alk_power = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    # 논문 Eq. (9): 시간별 H2 생산량은 전해조 입력전력에 비례한다.
    # 논문에서 사용하는 HHV 39 MWh/t과 정효율 0.682를 묶어
    # ALK_MWH_PER_T_H2 = 39 / 0.682 MWh/t로 정의했다.
    model.h2_production = pyo.Expression(
        model.T, rule=lambda m, t: m.alk_power[t] / ALK_MWH_PER_T_H2
    )
    model.h2_inventory = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.h2_tank_t = pyo.Var(domain=pyo.NonNegativeReals)
    model.h2_compressor_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.ro_mw = pyo.Var(domain=pyo.NonNegativeReals)

    # 논문 Eq. (5)의 최대 생산능력과 대응하는 전해조 입력전력 상한.
    # 1시간 간격이라 정격 MW와 시간당 MWh의 숫자가 같다.
    model.alk_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.alk_power[t] <= m.alk_mw
    )
    # 논문 Eq. (16): 이전 재고 + 전해조 생산 = 현재 재고 + HB 투입.
    # (t - 1) % len(T)는 t=0일 때 마지막 시간 재고를 가리키는 순환 경계다.
    # HB 투입은 논문 Sec. 3.4의 화학양론 6/34 × NH3 생산량으로 계산한다.
    model.h2_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.h2_inventory[t]
        == m.h2_inventory[(t - 1) % len(m.T)]
        + m.h2_production[t]
        - H2_T_PER_NH3_T * m.nh3[t],
    )
    # 논문 Eq. (20): 매시간 재고 <= 설치한 H2 탱크 용량.
    model.h2_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.h2_inventory[t] <= m.h2_tank_t
    )
    # 압축기·RO의 전력은 논문 Sec. 3.4의 단위 소비량 × H2 유량으로 계산한다.
    # 두 공정에 별도 번호식은 없고, 계산된 소비전력은 Eq. (1)에 들어간다.
    model.h2_compressor_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: H2_COMP_MWH_PER_T_H2 * m.h2_production[t]
        <= m.h2_compressor_mw,
    )
    model.ro_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: RO_MWH_PER_T_H2 * m.h2_production[t] <= m.ro_mw,
    )
