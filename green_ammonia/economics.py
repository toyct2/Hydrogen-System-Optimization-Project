from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import CRF, DISCOUNT_RATE, EQUIPMENT_COSTS, ModelSettings
from .replacement import add_alk_replacement


def add_annual_cost(model: pyo.ConcreteModel, settings: ModelSettings) -> None:
    """논문 Eq. (24)-(28)을 일정한 연간 생산량의 비용 최소화로 쓴다.

    CRF를 곱한 CAPEX는 연간 균등 비용이다. FOM은 매년 발생한다.
    배터리 교체 8/16/24년은 논문 가정이다. ALK 교체비는 기본
    시나리오에서 지정된 연도를 사용하고, MILP에서는 Eq. (22)의
    이진변수가 생산량에서 교체 연도를 결정한다.
    """
    # 논문 Eq. (26): 각 설비의 설치용량 × 단위 CAPEX를 합산한 초기 투자비.
    # EQUIPMENT_COSTS의 MW, MWh, t, t/h 단위는 각 설비 변수와 일치한다.
    capex = sum(
        getattr(model, name) * cost.capex_usd_per_unit
        for name, cost in EQUIPMENT_COSTS.items()
    )
    # 논문 Eq. (27): 설비별 고정 O&M은 해당 CAPEX의 연간 비율로 계산한다.
    fixed_om = sum(
        getattr(model, name) * cost.capex_usd_per_unit * cost.annual_om_fraction
        for name, cost in EQUIPMENT_COSTS.items()
    )
    battery_capex = (
        model.bess_mw * EQUIPMENT_COSTS["bess_mw"].capex_usd_per_unit
        + model.bess_mwh * EQUIPMENT_COSTS["bess_mwh"].capex_usd_per_unit
    )
    # 논문 Sec. 3.6의 BESS 8년 교체 가정: 8·16·24년 CAPEX를
    # Eq. (25)의 할인율로 현재가치화한다. 25년 말 재구매는 넣지 않는다.
    battery_replacement_pv = battery_capex * sum(
        (1 + DISCOUNT_RATE) ** -year for year in (8, 16, 24)
    )
    if settings.alk_replacement_milp:
        add_alk_replacement(model, settings)
    else:
        alk_replacement_pv = (
            0.4 * model.alk_mw * EQUIPMENT_COSTS["alk_mw"].capex_usd_per_unit
            * sum((1 + DISCOUNT_RATE) ** -year for year in settings.alk_replacement_years)
        )
        model.alk_replacement_pv = pyo.Expression(expr=alk_replacement_pv)
    # 논문 Eq. (27)의 계통 연결 용량요금과 구매 전력량요금.
    # 무계통 실행은 grid_mw=0이라 비용이 0이고, --grid 실행은 두 항을 최적화한다.
    grid_annual_cost = 72_000 * model.grid_mw + 65 * sum(
        model.grid[t] for t in model.T
    )
    model.initial_capex = pyo.Expression(expr=capex)
    model.fixed_om = pyo.Expression(expr=fixed_om)
    model.battery_replacement_pv = pyo.Expression(expr=battery_replacement_pv)
    model.grid_annual_cost = pyo.Expression(expr=grid_annual_cost)
    # 논문 Eqs. (24)-(28)의 LCOA 현재가치 식을 정액 연간비용으로 변환한다.
    # CRF × (초기 투자 + 교체비 PV) + 매년 고정비 + 매년 계통비.
    # 생산량이 매년 동일하므로 이 연간비용 최소화는 Eq. (28)의 LCOA
    # 최소화와 같은 최적 설비해를 준다. 논문의 변수비 W는 0이다.
    model.annual_cost = pyo.Expression(
        expr=CRF * (
            model.initial_capex + model.battery_replacement_pv
            + model.alk_replacement_pv
        ) + model.fixed_om + model.grid_annual_cost
    )
    # 1e6으로 나누는 것은 solver 수치 스케일용이며 최적해를 바꾸지 않는다.
    # 보고용 LCOA는 실행 파일에서 annual_cost / annual_ammonia_t로 구한다.
    model.objective = pyo.Objective(expr=model.annual_cost / 1_000_000)
