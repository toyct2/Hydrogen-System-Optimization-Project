from __future__ import annotations

import math
from pathlib import Path

import pyomo.environ as pyo

from green_ammonia.assumptions import (
    ALK_MWH_PER_T_H2,
    HB_MWH_PER_T_NH3,
    H2_T_PER_NH3_T,
    N2_T_PER_NH3_T,
    ModelSettings,
)
from green_ammonia.battery import physical_dispatch
from green_ammonia.design import build_design_model
from green_ammonia.ammonia import hb_production_fraction
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
    # Schmidhalter 논문 Eqs. (1), (16)-(18)과 Eq. (19)에 대응하는 배터리
    # 수지를 24시간 작은 사례로 검사한다. 배터리의 효율 배치는 논문과 다르다.
    # 1시간마다 같은 출하량과 항상 이용 가능한 풍력으로 실행을 빠르게 만든다.
    inputs = HourlyInputs((0.0,) * 24, (1.0,) * 24, (1.0,) * 24)
    settings = ModelSettings(fixed_hb_tph=1.0, grid_allowed=False)
    model = build_design_model(inputs, settings)
    solver = pyo.SolverFactory("appsi_highs")
    solution = solver.solve(model)

    assert solution.solver.termination_condition == pyo.TerminationCondition.optimal
    # Pyomo 등식 Constraint.body는 좌변-우변의 잔차를 반환한다.
    # 전력, H2, N2, NH3, 배터리 재고 식이 모두 0에 가까워야 한다.
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
    # N2 저장용량을 0으로 고정하면 Eq. (17)의 재고 변화가 0이므로
    # 매시간 ASU 생산량은 HB의 N2 소비량(28/34 t/t NH3)과 같아야 한다.
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
    # 배터리 후처리는 논문 Eq. (19)의 직접 구현이 아니라 출력 정리 단계다.
    # SOC 변화와 순 전력수지를 보존하고 동시 충방전을 없애는지 확인한다.
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


def test_hb_part_load_keeps_alk_efficiency_constant() -> None:
    inputs = HourlyInputs((0.0,) * 4, (1.0,) * 4, (1.0,) * 4)
    model = build_design_model(inputs, ModelSettings(part_load_efficiency=True))
    assert isinstance(model.h2_production, pyo.Expression)
    model.alk_mw.set_value(100)
    model.alk_power[0].set_value(30)
    model.alk_power[1].set_value(100)
    assert math.isclose(pyo.value(model.h2_production[0]), 30 / ALK_MWH_PER_T_H2)
    assert math.isclose(pyo.value(model.h2_production[1]), 100 / ALK_MWH_PER_T_H2)
    model.hb_tph.set_value(10)
    model.nh3[0].set_value(6)
    model.nh3[1].set_value(10)
    assert pyo.value(model.hb_power[0]) > 6 * HB_MWH_PER_T_NH3
    assert math.isclose(
        pyo.value(model.hb_power[1]), 10 * HB_MWH_PER_T_NH3, rel_tol=0.01
    )


def test_dynamic_part_load_case_solves_with_balances_and_ramps() -> None:
    inputs = HourlyInputs((0.0,) * 24, (1.0,) * 12 + (0.2,) * 12, (1.0,) * 24)
    settings = ModelSettings(part_load_efficiency=True, grid_allowed=False)
    model = build_design_model(inputs, settings)
    solution = pyo.SolverFactory("appsi_highs").solve(model)
    assert solution.solver.termination_condition == pyo.TerminationCondition.optimal
    for balance in (model.power_balance, model.h2_balance, model.n2_balance, model.nh3_balance):
        assert max(abs(pyo.value(balance[t].body)) for t in model.T) < 1e-6
    hb_capacity = pyo.value(model.hb_tph)
    for t in model.T:
        production = pyo.value(model.nh3[t])
        previous = pyo.value(model.nh3[(t - 1) % inputs.hours])
        assert production >= hb_production_fraction(0.6) * hb_capacity - 1e-6
        assert production <= hb_capacity + 1e-6
        power = pyo.value(model.hb_power[t])
        previous_power = pyo.value(model.hb_power[(t - 1) % inputs.hours])
        assert power - previous_power <= 0.02 * HB_MWH_PER_T_NH3 * hb_capacity + 1e-6
        assert previous_power - power <= 0.20 * HB_MWH_PER_T_NH3 * hb_capacity + 1e-6


def test_replacement_milp_selects_exact_crossing_years() -> None:
    # Given: Eq. (22)의 25년 반복 운전에서 여러 번 교체가 필요한 짧은 수명.
    inputs = HourlyInputs((0.0,) * 4, (1.0,) * 4, (1.0,) * 4)
    settings = ModelSettings(
        fixed_hb_tph=1.0, grid_allowed=False, alk_replacement_milp=True,
        alk_capacity_upper_bound_mw=50.0, alk_useful_hours=37.0,
    )
    model = build_design_model(inputs, settings)

    # When: 용량, 운전, 교체 연도를 하나의 MILP에서 함께 푼다.
    solution = pyo.SolverFactory("appsi_highs").solve(model)

    # Then: 정격 H2 생산량 기준 수명 경계를 넘은 첫해에만 비용이 붙는다.
    assert solution.solver.termination_condition == pyo.TerminationCondition.optimal
    capacity = pyo.value(model.alk_mw)
    annual_equivalent_hours = pyo.value(model.annual_h2_t) * ALK_MWH_PER_T_H2 / capacity
    expected = {
        (year, order)
        for order in model.replacement_orders for year in model.replacement_years
        if (year + 1) * annual_equivalent_hours > order * settings.alk_useful_hours + 1e-6
        and year * annual_equivalent_hours <= order * settings.alk_useful_hours + 1e-6
    }
    observed = {
        (year, order)
        for order in model.replacement_orders for year in model.replacement_years
        if pyo.value(model.replacement_mw[year, order]) > 0.5 * capacity
    }
    assert observed == expected
    assert len(observed) >= 2
    assert math.isclose(
        pyo.value(model.alk_replacement_pv),
        0.4 * 714_000 * capacity * sum(1.07 ** -year for year, _ in expected),
        rel_tol=1e-7,
    )


if __name__ == "__main__":
    test_public_weather_processing_matches_verified_benchmark()
    test_all_material_balances_close_on_small_solved_case()
    test_disabled_nitrogen_storage_forces_same_hour_production()
    test_battery_cleanup_preserves_state_and_power_balance()
    test_hb_part_load_keeps_alk_efficiency_constant()
    test_dynamic_part_load_case_solves_with_balances_and_ramps()
    test_replacement_milp_selects_exact_crossing_years()
    print("7 modular-model checks passed")
