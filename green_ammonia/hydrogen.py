from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import (
    ALK_MWH_PER_T_H2,
    H2_COMP_MWH_PER_T_H2,
    H2_T_PER_NH3_T,
    RO_MWH_PER_T_H2,
)


def add_hydrogen_system(model: pyo.ConcreteModel) -> None:
    """논문 Eq. (9), (16), (20)을 1시간 시간축에 추가한다.

    `alk_power[t]`는 MWh/h=MW이고 `h2_production[t]`는 t/h다.
    정효율 가정에서 생산량=전해조 입력전력/(39/0.682)이다.
    시간별 생산량에서 HB의 반응식상 수소 소비를 뺀 값이 재고 변화다.
    """
    model.alk_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.alk_power = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.h2_production = pyo.Expression(
        model.T, rule=lambda m, t: m.alk_power[t] / ALK_MWH_PER_T_H2
    )
    model.h2_inventory = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.h2_tank_t = pyo.Var(domain=pyo.NonNegativeReals)
    model.h2_compressor_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.ro_mw = pyo.Var(domain=pyo.NonNegativeReals)

    model.alk_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.alk_power[t] <= m.alk_mw
    )
    model.h2_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.h2_inventory[t]
        == m.h2_inventory[(t - 1) % len(m.T)]
        + m.h2_production[t]
        - H2_T_PER_NH3_T * m.nh3[t],
    )
    model.h2_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.h2_inventory[t] <= m.h2_tank_t
    )
    model.h2_compressor_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: H2_COMP_MWH_PER_T_H2 * m.h2_production[t]
        <= m.h2_compressor_mw,
    )
    model.ro_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: RO_MWH_PER_T_H2 * m.h2_production[t] <= m.ro_mw,
    )
