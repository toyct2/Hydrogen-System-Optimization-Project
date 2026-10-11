from __future__ import annotations

import math
from pathlib import Path

import pyomo.environ as pyo

from green_ammonia.assumptions import H2_T_PER_NH3_T, N2_T_PER_NH3_T, ModelSettings
from green_ammonia.battery import physical_dispatch
from green_ammonia.design import build_design_model
from green_ammonia.renewables import (
    HourlyInputs,
    cambridge_2013_inputs,
    read_newa_wind,
    read_pvgis_solar,
)


def test_public_weather_processing_matches_verified_benchmark() -> None:
    data = Path("data/benchmark_cambridge")
    inputs = cambridge_2013_inputs(data)
    solar = read_pvgis_solar(data / "pvgis_35.5_-0.5_2013_v52.json")
    wind = read_newa_wind(data / "newa_35.5_-0.5_2013.nc")
    assert inputs.hours == 8760
    assert inputs.solar_cf == solar
    assert inputs.wind_cf == wind
    assert math.isclose(sum(solar), 1610.20651, abs_tol=1e-8)
    assert math.isclose(sum(wind) / len(wind), 0.2195745624, abs_tol=1e-10)
    assert math.isclose(inputs.annual_ammonia_t, 83_950, abs_tol=1e-7)


def test_all_material_balances_close_on_small_solved_case() -> None:
    inputs = HourlyInputs((0.0,) * 24, (1.0,) * 24, (1.0,) * 24)
    settings = ModelSettings(fixed_hb_tph=1.0, grid_allowed=False)
    model = build_design_model(inputs, settings)
    solver = pyo.SolverFactory("appsi_highs")
    solution = solver.solve(model)

    assert solution.solver.termination_condition == pyo.TerminationCondition.optimal
    for balance in (
        model.power_balance,
        model.h2_balance,
        model.n2_balance,
        model.nh3_balance,
        model.bess_balance,
    ):
        assert max(abs(pyo.value(balance[t].body)) for t in model.T) < 1e-7
    assert math.isclose(
        sum(pyo.value(model.h2_production[t]) for t in model.T),
        H2_T_PER_NH3_T * inputs.annual_ammonia_t,
        abs_tol=1e-7,
    )
    assert math.isclose(
        sum(pyo.value(model.n2_production[t]) for t in model.T),
        N2_T_PER_NH3_T * inputs.annual_ammonia_t,
        abs_tol=1e-7,
    )
    assert pyo.value(model.grid_mw) == 0


def test_disabled_nitrogen_storage_forces_same_hour_production() -> None:
    inputs = HourlyInputs((0.0,) * 4, (1.0,) * 4, (1.0,) * 4)
    model = build_design_model(
        inputs, ModelSettings(fixed_hb_tph=1.0, grid_allowed=False, nitrogen_storage_enabled=False)
    )
    solution = pyo.SolverFactory("appsi_highs").solve(model)

    assert solution.solver.termination_condition == pyo.TerminationCondition.optimal
    assert pyo.value(model.n2_tank_t) == 0
    for t in model.T:
        assert math.isclose(pyo.value(model.n2_production[t]), N2_T_PER_NH3_T, abs_tol=1e-7)


def test_battery_cleanup_preserves_state_and_power_balance() -> None:
    efficiency = 0.9
    for charge, discharge in ((10.0, 3.0), (2.0, 10.0)):
        physical = physical_dispatch(charge, discharge, efficiency)
        original_soc_change = math.sqrt(efficiency) * charge - discharge / math.sqrt(efficiency)
        cleaned_soc_change = (
            math.sqrt(efficiency) * physical.charge_mw
            - physical.discharge_mw / math.sqrt(efficiency)
        )
        assert math.isclose(original_soc_change, cleaned_soc_change, abs_tol=1e-10)
        assert math.isclose(
            charge - discharge,
            physical.charge_mw - physical.discharge_mw + physical.extra_curtail_mw,
            abs_tol=1e-10,
        )
        assert physical.charge_mw == 0 or physical.discharge_mw == 0


if __name__ == "__main__":
    test_public_weather_processing_matches_verified_benchmark()
    test_all_material_balances_close_on_small_solved_case()
    test_disabled_nitrogen_storage_forces_same_hour_production()
    test_battery_cleanup_preserves_state_and_power_balance()
    print("4 modular-model checks passed")
