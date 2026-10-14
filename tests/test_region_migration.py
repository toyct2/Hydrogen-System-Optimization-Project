from __future__ import annotations

from math import isclose

import pyomo.environ as pyo

from green_ammonia.ammonia import hb_production_fraction
from green_ammonia.assumptions import HB_MWH_PER_T_NH3, ModelSettings
from green_ammonia.design import build_design_model
from green_ammonia.region_migration import (
    _classify_constant_efficiency_model,
    classify_production_fraction,
    solve_region_migration_experiment,
)
from green_ammonia.renewables import HourlyInputs


def test_assigned_region_does_not_bound_new_production() -> None:
    # Given: 모든 시각의 할선을 OR0에서 고르되 0.8 부하 경계 바로 위를 검사한다.
    inputs = HourlyInputs((0.0,) * 4, (1.0,) * 4, (1.0,) * 4)
    settings = ModelSettings(part_load_efficiency=True, grid_allowed=False)
    model = build_design_model(inputs, settings, (0,) * 4)
    boundary = hb_production_fraction(0.8)

    # When: OR1에 속하는 생산율을 OR0 할선에 대입한다.
    model.hb_tph.set_value(10)
    model.nh3[0].set_value(10 * (boundary + 0.01))
    load = pyo.value(model.hb_power[0]) / (10 * HB_MWH_PER_T_NH3)

    # Then: 구간별 생산율 경계는 없고 실제 전력부하만 60~100%로 제한한다.
    assert not hasattr(model, "hb_region_lower")
    assert not hasattr(model, "hb_region_upper")
    assert 0.6 <= load <= 1.0
    assert pyo.value(model.hb_power_lower[0].body) <= 0
    assert pyo.value(model.hb_power_upper[0].body) <= 0


def test_exact_boundary_keeps_previously_assigned_region() -> None:
    # Given: 두 운전영역이 만나는 80% 전력부하의 생산율.
    boundary = hb_production_fraction(0.8)

    # When: 이전 구간이 서로 다른 두 해를 경계점에서 재분류한다.
    lower, lower_tie = classify_production_fraction(boundary, 0.6, 0)
    upper, upper_tie = classify_production_fraction(boundary, 0.6, 1)
    moved, moved_tie = classify_production_fraction(boundary + 1e-5, 0.6, 0)

    # Then: 정확한 경계에서만 이전 구간을 유지하고 이동은 허용한다.
    assert (lower, lower_tie) == (0, True)
    assert (upper, upper_tie) == (1, True)
    assert (moved, moved_tie) == (1, False)


def test_constant_efficiency_lp_uses_power_load_boundaries() -> None:
    inputs = HourlyInputs((0.0,) * 4, (1.0,) * 4, (1.0,) * 4)
    settings = ModelSettings(part_load_efficiency=False)
    model = build_design_model(inputs, settings)
    model.hb_tph.set_value(10)
    for hour, production in enumerate((6.0, 7.0, 8.1, 9.0)):
        model.nh3[hour].set_value(production)
    assert _classify_constant_efficiency_model(model, settings) == (0, 0, 1, 1)


def test_hb_only_part_load_keeps_alk_constant_efficiency() -> None:
    inputs = HourlyInputs((0.0,) * 4, (1.0,) * 4, (1.0,) * 4)
    settings = ModelSettings(part_load_efficiency=True)
    model = build_design_model(inputs, settings, (0, 1, 0, 1))
    assert not hasattr(model, "alk_part_load_peak")
    assert not hasattr(model, "alk_part_load_rated")
    assert isinstance(model.h2_production, pyo.Expression)
    model.alk_power[0].set_value(1)
    assert isclose(pyo.value(model.h2_production[0]), 1 / (39 / 0.682))
    model.hb_tph.set_value(10)
    model.nh3[0].set_value(5)
    model.nh3[1].set_value(5)
    assert not isclose(pyo.value(model.hb_power[0]), pyo.value(model.hb_power[1]))


def test_three_stage_grid_milp_keeps_alk_constant_efficiency() -> None:
    # Given: 24시간의 작은 입력에서 계통 구매와 Eq. (22) 교체 이진변수를 켠다.
    inputs = HourlyInputs((0.0,) * 24, (1.0,) * 12 + (0.2,) * 12, (1.0,) * 24)
    settings = ModelSettings(
        part_load_efficiency=True,
        alk_replacement_milp=True,
        grid_allowed=True,
    )

    # When: 예비 LP로 유한 상한을 만든 뒤 0차 MILP와 1·2차를 푼다.
    result = solve_region_migration_experiment(
        inputs, settings, refinements=2, time_limit_per_stage=60
    )

    # Then: 저장되는 단계는 정확히 세 개이고 ALK는 Eq. (9) 정효율이다.
    assert tuple(stage.iteration for stage in result.stages) == (0, 1, 2)
    assert hasattr(result.model, "replacement_reached")
    assert not hasattr(result.model, "alk_part_load_peak")
    assert isinstance(result.model.h2_production, pyo.Expression)
    assert result.model.alk_mw.ub is not None
    assert pyo.value(result.model.alk_mw) < result.model.alk_mw.ub
    assert pyo.value(result.model.grid_mw) >= 0
    assert all(stage.minimum_hb_load >= 0.6 - 1e-7 for stage in result.stages[1:])
    assert all(stage.maximum_hb_load <= 1.0 + 1e-7 for stage in result.stages[1:])


if __name__ == "__main__":
    test_assigned_region_does_not_bound_new_production()
    test_exact_boundary_keeps_previously_assigned_region()
    test_constant_efficiency_lp_uses_power_load_boundaries()
    test_hb_only_part_load_keeps_alk_constant_efficiency()
    test_three_stage_grid_milp_keeps_alk_constant_efficiency()
    print("5 region-migration checks passed")
