from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import N2_COMP_MWH_PER_T_N2, N2_T_PER_NH3_T


def add_nitrogen_system(model: pyo.ConcreteModel, storage_enabled: bool) -> None:
    """논문 Eq. (12), (17)의 N2 버퍼를 구현한다.

    ASU 생산량은 HB가 그 시간에 소비하는 질소량과 다를 수 있다.
    차이는 질소 탱크 재고에 들어가며 연말 재고는 연초와 같다.
    storage_enabled=False이면 질소 탱크용량을 0으로 고정한다.
    """
    model.asu_tph = pyo.Var(domain=pyo.NonNegativeReals)
    model.n2_production = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.n2_compressor_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.n2_inventory = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.n2_tank_t = pyo.Var(domain=pyo.NonNegativeReals)

    model.asu_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.n2_production[t] <= m.asu_tph
    )
    model.n2_compressor_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: N2_COMP_MWH_PER_T_N2 * m.n2_production[t]
        <= m.n2_compressor_mw,
    )
    model.n2_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.n2_inventory[t]
        == m.n2_inventory[(t - 1) % len(m.T)]
        + m.n2_production[t]
        - N2_T_PER_NH3_T * m.nh3[t],
    )
    model.n2_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.n2_inventory[t] <= m.n2_tank_t
    )
    if not storage_enabled:
        model.n2_tank_t.fix(0)
