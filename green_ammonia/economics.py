from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import CRF, DISCOUNT_RATE, EQUIPMENT_COSTS, ModelSettings


def add_annual_cost(model: pyo.ConcreteModel, settings: ModelSettings) -> None:
    """논문 Eq. (24)-(28)을 일정한 연간 생산량의 비용 최소화로 쓴다.

    CRF를 곱한 CAPEX는 연간 균등 비용이다. FOM은 매년 발생한다.
    배터리 교체 8/16/24년은 논문 가정이다. ALK 교체 연도는
    최적화 결과의 누적 등가 전부하시간을 확인해 시나리오에서 지정한다.
    """
    capex = sum(
        getattr(model, name) * cost.capex_usd_per_unit
        for name, cost in EQUIPMENT_COSTS.items()
    )
    fixed_om = sum(
        getattr(model, name) * cost.capex_usd_per_unit * cost.annual_om_fraction
        for name, cost in EQUIPMENT_COSTS.items()
    )
    battery_capex = (
        model.bess_mw * EQUIPMENT_COSTS["bess_mw"].capex_usd_per_unit
        + model.bess_mwh * EQUIPMENT_COSTS["bess_mwh"].capex_usd_per_unit
    )
    battery_replacement_pv = battery_capex * sum(
        (1 + DISCOUNT_RATE) ** -year for year in (8, 16, 24)
    )
    alk_replacement_pv = (
        0.4 * model.alk_mw * EQUIPMENT_COSTS["alk_mw"].capex_usd_per_unit
        * sum((1 + DISCOUNT_RATE) ** -year for year in settings.alk_replacement_years)
    )
    grid_annual_cost = 72_000 * model.grid_mw + 65 * sum(
        model.grid[t] for t in model.T
    )
    model.initial_capex = pyo.Expression(expr=capex)
    model.fixed_om = pyo.Expression(expr=fixed_om)
    model.battery_replacement_pv = pyo.Expression(expr=battery_replacement_pv)
    model.alk_replacement_pv = pyo.Expression(expr=alk_replacement_pv)
    model.grid_annual_cost = pyo.Expression(expr=grid_annual_cost)
    model.annual_cost = pyo.Expression(
        expr=CRF * (
            model.initial_capex + model.battery_replacement_pv
            + model.alk_replacement_pv
        ) + model.fixed_om + model.grid_annual_cost
    )
    model.objective = pyo.Objective(expr=model.annual_cost / 1_000_000)
