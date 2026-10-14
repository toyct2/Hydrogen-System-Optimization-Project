# /// script
# requires-python = ">=3.11"
# dependencies = ["pyomo", "highspy", "numpy", "scipy"]
# ///

"""전해조 교체 MILP와 HB 부분부하 0·1·2차 비교를 실행한다."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pyomo.environ as pyo

from green_ammonia.assumptions import ModelSettings
from green_ammonia.region_migration import RegionStage, solve_region_migration_experiment
from green_ammonia.renewables import cambridge_2013_inputs


PROJECT_DIR = Path(__file__).resolve().parent
DATA = PROJECT_DIR / "data" / "benchmark_cambridge"
OUTPUT = PROJECT_DIR / "results" / "cambridge_2013_hb_region_milp_0_to_2"


def save_stage(stage: RegionStage, regions: tuple[int, ...]) -> None:
    """각 단계의 OR 배정을 남겨 선형화 반복을 재현할 수 있게 한다."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"stage_{stage.iteration}.json").write_text(
        json.dumps({"stage": asdict(stage), "regions": regions}, ensure_ascii=False),
        encoding="utf-8",
    )


def load_saved_stages(hours: int) -> tuple[tuple[RegionStage, ...], tuple[tuple[int, ...], ...]]:
    stages: list[RegionStage] = []
    history: list[tuple[int, ...]] = []
    for iteration in range(3):
        path = OUTPUT / f"stage_{iteration}.json"
        if not path.exists():
            break
        saved = json.loads(path.read_text(encoding="utf-8"))
        stage_data = saved["stage"]
        stage = RegionStage(**{**stage_data, "region_counts": tuple(stage_data["region_counts"])})
        regions = tuple(saved["regions"])
        if (
            stage.iteration != iteration
            or len(regions) != hours
            or stage.region_counts != (regions.count(0), regions.count(1))
        ):
            raise ValueError(f"저장된 {iteration}차의 운전구간 기록이 잘못됐습니다")
        stages.append(stage)
        history.append(regions)
    if not stages or len(stages) == 3:
        raise ValueError("이어 풀 수 있는 미완료 0·1차 결과가 없습니다")
    return tuple(stages), tuple(history)


def main(*, resume: bool = False) -> None:
    inputs = cambridge_2013_inputs(DATA)
    settings = ModelSettings(
        solar_delivery_factor=1.0,
        grid_allowed=True,
        fixed_hb_tph=None,
        part_load_efficiency=True,
        alk_replacement_milp=True,
    )
    # Eq. (9)의 정효율 전해조는 전 단계에서 유지한다. Eq. (22)의
    # 교체 이진변수는 0차부터 적용하고, HB Fig. 5/식 (15)의 구간별
    # 전력식만 1·2차에 추가한다. 계통은 식 (23), (27)을 따른다.
    saved_stages, saved_regions = load_saved_stages(inputs.hours) if resume else (None, None)
    experiment = solve_region_migration_experiment(
        inputs, settings, refinements=2, time_limit_per_stage=2400,
        stage_callback=save_stage,
        resume_stages=saved_stages, resume_region_history=saved_regions,
    )
    model = experiment.model
    replacement_years = tuple(
        year
        for year in model.replacement_years
        for order in model.replacement_orders
        if pyo.value(model.replacement_reached[year, order]) > 0.5
        and (year == 1 or pyo.value(model.replacement_reached[year - 1, order]) < 0.5)
    )
    capacity_bound = model.alk_mw.ub
    assert capacity_bound is not None
    summary = {
        "scenario": "2013 Cambridge; HB part-load; ALK constant efficiency; replacement MILP; grid on",
        "hours": inputs.hours,
        "stages": [asdict(stage) for stage in experiment.stages],
        "converged_all_hourly_regions": experiment.converged,
        "settings": {
            "hb_part_load_efficiency": settings.part_load_efficiency,
            "alk_part_load_efficiency": False,
            "alk_replacement_milp": settings.alk_replacement_milp,
            "grid_allowed": settings.grid_allowed,
            "mip_relative_gap_tolerance": 0.001,
        },
        "alk_capacity_upper_bound_mw": capacity_bound,
        "alk_capacity_bound_use_fraction": pyo.value(model.alk_mw) / capacity_bound,
        "alk_replacement_years": replacement_years,
        "alk_replacement_present_value_usd": pyo.value(model.alk_replacement_pv),
        "capacities": {
            "solar_mw": pyo.value(model.solar_mw),
            "wind_mw": pyo.value(model.wind_mw),
            "alk_mw": pyo.value(model.alk_mw),
            "hb_tph": pyo.value(model.hb_tph),
            "h2_tank_t": pyo.value(model.h2_tank_t),
            "n2_tank_t": pyo.value(model.n2_tank_t),
            "nh3_tank_t": pyo.value(model.nh3_tank_t),
            "bess_mw": pyo.value(model.bess_mw),
            "bess_mwh": pyo.value(model.bess_mwh),
            "grid_mw": pyo.value(model.grid_mw),
        },
        "annual_grid_purchase_mwh": sum(pyo.value(model.grid[t]) for t in model.T),
        "maximum_power_balance_error_mw": max(
            abs(pyo.value(model.power_balance[t].body)) for t in model.T
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    with (OUTPUT / "hourly_regions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("hour", "stage_0", "stage_1", "stage_2"))
        writer.writerows(
            (hour,) + tuple(regions[hour] for regions in experiment.region_history)
            for hour in range(inputs.hours)
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--resume"]):
        raise ValueError("사용법: python run_hb_region_milp.py [--resume]")
    main(resume="--resume" in sys.argv[1:])
