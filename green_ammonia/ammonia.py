from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import ModelSettings
from .renewables import HourlyInputs


def add_ammonia_system(model: pyo.ConcreteModel, inputs: HourlyInputs, settings: ModelSettings) -> None:
    """HB40은 최대용량 대비 40% 감산, 즉 최소 부하 60%로 해석한다.

    Eq. (18): 재고[t] = 재고[t-1] + 생산[t] - 출하[t].
    1시간 간격이므로 t/h 생산률의 수치가 해당 시간 생산 t와 같다.
    첫 시간의 직전 재고를 마지막 시간 재고로 두어 연간 순환시킨다.
    """
    model.hb_tph = pyo.Var(domain=pyo.NonNegativeReals)
    model.nh3 = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.nh3_tank_t = pyo.Var(domain=pyo.NonNegativeReals)
    model.nh3_inventory = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.hb_upper = pyo.Constraint(
        model.T, rule=lambda m, t: m.nh3[t] <= m.hb_tph
    )
    model.hb_lower = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.nh3[t] >= settings.hb_minimum_fraction * m.hb_tph,
    )
    model.hb_ramp_up = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.nh3[t] - m.nh3[(t - 1) % inputs.hours]
        <= settings.hb_ramp_up_fraction * m.hb_tph,
    )
    model.hb_ramp_down = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.nh3[(t - 1) % inputs.hours] - m.nh3[t]
        <= settings.hb_ramp_down_fraction * m.hb_tph,
    )
    model.nh3_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.nh3_inventory[t]
        == m.nh3_inventory[(t - 1) % inputs.hours]
        + m.nh3[t] - inputs.delivery_tph[t],
    )
    model.nh3_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.nh3_inventory[t] <= m.nh3_tank_t
    )
    if settings.fixed_hb_tph is not None:
        model.hb_tph.fix(settings.fixed_hb_tph)
        model.nh3_tank_t.fix(0)
        for t in model.T:
            model.nh3[t].fix(settings.fixed_hb_tph)
