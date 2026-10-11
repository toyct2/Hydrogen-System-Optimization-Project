from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import (
    ASU_MWH_PER_T_N2,
    H2_COMP_MWH_PER_T_H2,
    HB_MWH_PER_T_NH3,
    ModelSettings,
    N2_COMP_MWH_PER_T_N2,
    RO_MWH_PER_T_H2,
)
from .renewables import HourlyInputs


def add_electricity_bus(model: pyo.ConcreteModel, inputs: HourlyInputs, settings: ModelSettings) -> None:
    """논문 Eq. (1): 발전·계통·방전 = 공정·충전·출력제한.

    1시간 간격이므로 MW 출력과 그 시간의 MWh 에너지는 수치가 같다.
    PV·풍력 용량계수는 파일에서 읽고 설비 MW를 곱해 발전량을 만든다.
    `curtail`은 쓰지 않은 잉여 전력으로, 수지를 항상 등식으로 만든다.
    """
    model.solar_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.wind_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.grid_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.grid = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.curtail = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    if not settings.grid_allowed:
        model.grid_mw.fix(0)

    model.grid_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.grid[t] <= m.grid_mw
    )
    model.grid_green_limit = pyo.Constraint(
        expr=model.grid_mw <= 0.01 * (
            model.bess_mw + model.alk_mw + model.h2_compressor_mw
            + model.ro_mw + model.asu_tph * ASU_MWH_PER_T_N2
            + model.n2_compressor_mw + model.hb_tph * HB_MWH_PER_T_NH3
        )
    )

    def hourly_balance(m: pyo.ConcreteModel, t: int) -> pyo.EqualityExpression:
        renewable = (
            settings.solar_delivery_factor * inputs.solar_cf[t] * m.solar_mw
            + settings.wind_delivery_factor * inputs.wind_cf[t] * m.wind_mw
        )
        hydrogen_process = (
            m.alk_power[t]
            + (H2_COMP_MWH_PER_T_H2 + RO_MWH_PER_T_H2) * m.h2_production[t]
        )
        nitrogen_process = (
            (ASU_MWH_PER_T_N2 + N2_COMP_MWH_PER_T_N2) * m.n2_production[t]
        )
        ammonia_process = HB_MWH_PER_T_NH3 * m.nh3[t]
        return renewable + m.grid[t] + m.bess_discharge[t] == (
            hydrogen_process + nitrogen_process + ammonia_process
            + m.bess_charge[t] + m.curtail[t]
        )

    model.power_balance = pyo.Constraint(model.T, rule=hourly_balance)
