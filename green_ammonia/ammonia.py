from __future__ import annotations

from math import sqrt
from typing import Final

import pyomo.environ as pyo

from .assumptions import (
    HB_MWH_PER_T_NH3,
    HB_PART_LOAD_ALPHA,
    ModelSettings,
)
from .renewables import HourlyInputs


HB_REGION_LOAD_BOUNDARIES: Final = (0.15, 0.40, 0.60, 0.80, 1.0)


def hb_production_fraction(load_fraction: float) -> float:
    """논문 Fig. 5의 생산율-전력부하 곡선에서 정규화된 생산율을 구한다.

    원본 Eq. (14)의 인쇄된 효율식은 Fig. 5와 직접 대입 시 모순된다.
    기존 구현이 사용한 q=f²/[1+alpha*f*(1-f)]를 유지하고 Fig. 5에
    대응하는 곡선으로 취급한다. 따라서 원 논문의 원계수와 동일한
    식이라고 주장하지 않으며, 이 차이는 변경 기록에 명시한다.
    """
    return load_fraction**2 / (
        1 + HB_PART_LOAD_ALPHA * load_fraction * (1 - load_fraction)
    )


def hb_load_fraction(production_fraction: float) -> float:
    """Fig. 5의 q=f²/[1+alpha*f*(1-f)]를 양의 근으로 역변환한다."""
    alpha = HB_PART_LOAD_ALPHA
    return (
        alpha * production_fraction
        + sqrt((alpha * production_fraction) ** 2
               + 4 * production_fraction * (1 + alpha * production_fraction))
    ) / (2 * (1 + alpha * production_fraction))


def hb_region_points(minimum_load: float) -> tuple[float, ...]:
    """논문 Eq. (15)의 OR 경계를 현재 HB 최소 전력부하에서 자른다."""
    return (minimum_load,) + tuple(
        point for point in HB_REGION_LOAD_BOUNDARIES if minimum_load < point < 1
    ) + (1.0,)


def hb_region_for_production(production_fraction: float, minimum_load: float) -> int:
    """이전 풀이의 생산율에 해당하는 Eq. (15) 운전 영역을 선택한다."""
    points = hb_region_points(minimum_load)
    for index in range(len(points) - 2):
        if production_fraction <= hb_production_fraction(points[index + 1]):
            return index
    return len(points) - 2


def add_ammonia_system(
    model: pyo.ConcreteModel, inputs: HourlyInputs, settings: ModelSettings,
    hb_regions: tuple[int, ...] | None = None,
) -> None:
    """HB40은 최대용량 대비 40% 감산, 즉 최소 부하 60%로 해석한다.

    Eq. (18): 재고[t] = 재고[t-1] + 생산[t] - 출하[t].
    1시간 간격이므로 t/h 생산률의 수치가 해당 시간 생산 t와 같다.
    첫 시간의 직전 재고를 마지막 시간 재고로 두어 연간 순환시킨다.
    """
    model.hb_tph = pyo.Var(domain=pyo.NonNegativeReals)
    model.nh3 = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.nh3_tank_t = pyo.Var(domain=pyo.NonNegativeReals)
    model.nh3_inventory = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    if settings.part_load_efficiency:
        points = hb_region_points(settings.hb_minimum_fraction)
        if hb_regions is not None and len(hb_regions) != inputs.hours:
            raise ValueError("HB 운전영역 개수와 시간 수가 다릅니다")
        # 논문 Fig. 6/Eq. (15): 이전 해의 각 시각을 OR에 배정해
        # Fig. 5 기반 할선의 기울기와 절편을 고른다.
        def part_load_power(m: pyo.ConcreteModel, t: int):
            if hb_regions is None:
                first, last = points[0], points[-1]
            else:
                region = hb_regions[t]
                if not 0 <= region < len(points) - 1:
                    raise ValueError("HB 운전영역 번호가 범위를 벗어났습니다")
                first, last = points[region], points[region + 1]
            q_first, q_last = hb_production_fraction(first), hb_production_fraction(last)
            slope = (last - first) / (q_last - q_first)
            intercept = first - slope * q_first
            return HB_MWH_PER_T_NH3 * (slope * m.nh3[t] + intercept * m.hb_tph)

        model.hb_power = pyo.Expression(model.T, rule=part_load_power)
        # 이전 해의 OR은 논문 Eq. (15)의 할선 기울기와 절편만 선택한다.
        # OR별 생산량 경계는 두지 않으므로 다음 해에서 OR 이동이 가능하다.
        # 이는 원 논문의 구간 내 근사에서 벗어나는 실험 설정이다.
        # 대신 실제 전력부하 f=hb_power/(0.311×hb_tph)를 60~100%로 제한한다.
        model.hb_power_lower = pyo.Constraint(
            model.T,
            rule=lambda m, t: m.hb_power[t]
            >= settings.hb_minimum_fraction * HB_MWH_PER_T_NH3 * m.hb_tph,
        )
        model.hb_power_upper = pyo.Constraint(
            model.T,
            rule=lambda m, t: m.hb_power[t]
            <= HB_MWH_PER_T_NH3 * m.hb_tph,
        )
    else:
        model.hb_power = pyo.Expression(
            model.T, rule=lambda m, t: HB_MWH_PER_T_NH3 * m.nh3[t]
        )
    # HB 정격용량과 최소 부하율은 논문 Sec. 3.3.3의 운전범위를 구현한다.
    # HB40은 정격의 40% 감산 가능, 즉 최소 부하 60%로 해석한다.
    model.hb_upper = pyo.Constraint(
        model.T, rule=lambda m, t: m.nh3[t] <= m.hb_tph
    )
    # 논문 Sec. 3.3.3의 40% turn-down은 전력부하 f>=0.60이다.
    # 부분부하 때 NH3 생산율 q는 f와 다르므로 q(f_min)를 사용한다.
    minimum_production = (
        hb_production_fraction(settings.hb_minimum_fraction)
        if settings.part_load_efficiency else settings.hb_minimum_fraction
    )
    model.hb_lower = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.nh3[t] >= minimum_production * m.hb_tph,
    )
    # 논문 Sec. 3.3.3의 시간당 상향 2%·하향 20% 램프 한도.
    # 앞 시간에 (t - 1) % hours를 써 연말과 연초의 운전도 연결한다.
    model.hb_ramp_up = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.hb_power[t] - m.hb_power[(t - 1) % inputs.hours]
        <= settings.hb_ramp_up_fraction * HB_MWH_PER_T_NH3 * m.hb_tph,
    )
    model.hb_ramp_down = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.hb_power[(t - 1) % inputs.hours] - m.hb_power[t]
        <= settings.hb_ramp_down_fraction * HB_MWH_PER_T_NH3 * m.hb_tph,
    )
    # 논문 Eq. (18): 이전 NH3 재고 + HB 생산 = 현재 재고 + 출하.
    # 논문 Eq. (21)의 14일 주기·48시간 선적 제약 대신 입력 delivery_tph를 쓴다.
    # 현재 입력은 매시간 230/24 t을 출하한다.
    model.nh3_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.nh3_inventory[t]
        == m.nh3_inventory[(t - 1) % inputs.hours]
        + m.nh3[t] - inputs.delivery_tph[t],
    )
    # Eq. (20)의 H2 용량 부등식과 같은 방식으로 NH3 탱크용량을 제한한다.
    model.nh3_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.nh3_inventory[t] <= m.nh3_tank_t
    )
    if settings.fixed_hb_tph is not None:
        model.hb_tph.fix(settings.fixed_hb_tph)
        model.nh3_tank_t.fix(0)
        for t in model.T:
            model.nh3[t].fix(settings.fixed_hb_tph)
