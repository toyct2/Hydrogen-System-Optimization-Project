"""Schmidhalter et al. (2025) Eq. (22)의 전해조 교체 연도 MILP."""

from __future__ import annotations

from math import ceil

import pyomo.environ as pyo

from .assumptions import (
    ALK_PEAK_EFFICIENCY,
    ALK_RATED_EFFICIENCY,
    DISCOUNT_RATE,
    EQUIPMENT_COSTS,
    PROJECT_YEARS,
    ModelSettings,
)
from .errors import InvalidModelInput


def add_alk_replacement(model: pyo.ConcreteModel, settings: ModelSettings) -> None:
    """연간 대표 운전이 25년 반복될 때 교체 횟수와 연도를 함께 결정한다.

    Eq. (22)의 기준 생산량은 C[MW] × UL[h] × eta_rated / HHV[MWh/t]다.
    연간 H2 생산량을 이 기준으로 나눈 등가 전부하시간으로 비교한다.
    이산변수 reached[j,k]는 j년 말까지 k번째 수명 경계를 넘었음을 뜻한다.
    논문 Eq. (22)의 jH <= k UL C < (j+1)H를 따라 j년 말에 비용을
    잡는다. (j+1)H > k UL C 이면 reached[j,k]=1이 강제된다.
    교체비가 양수이므로 불필요하게 일찍 1로 만드는 해는 최적이 아니다.
    최종 사업연도 뒤에만 필요한 교체비는 포함하지 않는다.

    Eq. (27)의 40% 교체비는 C × event[j,k]의 곱이다. event는 이웃한
    reached의 차이이며, replacement_mw의 세 표준 부등식이 이 곱을
    정확하게 선형화한다. Big-M은 지정된 C 상한과 최대 시간별 생산능력
    (Eq. (5), 최대 부분부하 효율)로 계산한다. 임의의 무한대는 사용하지 않는다.
    """
    capacity_bound = settings.alk_capacity_upper_bound_mw
    if capacity_bound is None:
        raise InvalidModelInput("MILP 모델을 조립하기 전에 전해조 용량 상한을 정해야 합니다")
    model.alk_mw.setub(capacity_bound)
    model.annual_h2_t = pyo.Var(domain=pyo.NonNegativeReals)
    model.annual_h2_total = pyo.Constraint(
        expr=model.annual_h2_t == sum(model.h2_production[t] for t in model.T)
    )
    # 정격 생산량으로 환산한 연간 사용량을 수명으로 나누면 단위가 MW가 된다.
    rated_mwh_per_t = 39 / ALK_RATED_EFFICIENCY
    equivalent_mw = rated_mwh_per_t / settings.alk_useful_hours
    max_events = ceil(
        PROJECT_YEARS * len(model.T) * ALK_PEAK_EFFICIENCY
        / (ALK_RATED_EFFICIENCY * settings.alk_useful_hours)
    )
    model.replacement_years = pyo.RangeSet(1, PROJECT_YEARS - 1)
    model.replacement_orders = pyo.RangeSet(1, max_events)
    model.replacement_reached = pyo.Var(
        model.replacement_years, model.replacement_orders, domain=pyo.Binary
    )
    model.replacement_mw = pyo.Var(
        model.replacement_years, model.replacement_orders, domain=pyo.NonNegativeReals
    )

    def event(m: pyo.ConcreteModel, year: int, order: int):
        previous = 0 if year == 1 else m.replacement_reached[year - 1, order]
        return m.replacement_reached[year, order] - previous

    # 한 번 도달한 수명 경계는 이후 해에 유지되며, k번째 교체 전에
    # k-1번째 교체가 먼저 발생해야 한다.
    model.replacement_chronology = pyo.Constraint(
        model.replacement_years, model.replacement_orders,
        rule=lambda m, j, k: m.replacement_reached[j, k]
        >= (0 if j == 1 else m.replacement_reached[j - 1, k]),
    )
    model.replacement_ordering = pyo.Constraint(
        model.replacement_years, model.replacement_orders,
        rule=lambda m, j, k: pyo.Constraint.Skip if k == 1
        else m.replacement_reached[j, k] <= m.replacement_reached[j, k - 1],
    )
    # 다음 해의 사용량이 경계를 초과하면 해당 연도 말까지 교체가 필수다. Big-M을
    # 정격 대비 가능한 최대 생산량과 C 상한에서 도출해 유효성을 보장한다.
    model.replacement_lifetime = pyo.Constraint(
        model.replacement_years, model.replacement_orders,
        rule=lambda m, j, k: (j + 1) * equivalent_mw * m.annual_h2_t
        <= k * m.alk_mw + (
            (j + 1) * len(m.T) * ALK_PEAK_EFFICIENCY
            / (ALK_RATED_EFFICIENCY * settings.alk_useful_hours)
            * capacity_bound
        ) * m.replacement_reached[j, k],
    )
    model.replacement_product_upper_capacity = pyo.Constraint(
        model.replacement_years, model.replacement_orders,
        rule=lambda m, j, k: m.replacement_mw[j, k] <= m.alk_mw,
    )
    model.replacement_product_upper_event = pyo.Constraint(
        model.replacement_years, model.replacement_orders,
        rule=lambda m, j, k: m.replacement_mw[j, k] <= capacity_bound * event(m, j, k),
    )
    model.replacement_product_lower = pyo.Constraint(
        model.replacement_years, model.replacement_orders,
        rule=lambda m, j, k: m.replacement_mw[j, k]
        >= m.alk_mw - capacity_bound * (1 - event(m, j, k)),
    )
    # Eq. (25)의 연도별 현재가치와 Eq. (27)의 교체비 40%를 결합한다.
    model.alk_replacement_pv = pyo.Expression(
        expr=0.4 * EQUIPMENT_COSTS["alk_mw"].capex_usd_per_unit
        * sum(
            model.replacement_mw[j, k] / (1 + DISCOUNT_RATE) ** j
            for j in model.replacement_years for k in model.replacement_orders
        )
    )
