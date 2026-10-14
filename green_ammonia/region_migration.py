"""HB 운전영역 재선형화와 전해조 교체 MILP의 단계별 풀이."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, isclose
from typing import Callable

import pyomo.environ as pyo

from .ammonia import (
    hb_load_fraction,
    hb_production_fraction,
    hb_region_for_production,
    hb_region_points,
)
from .assumptions import (
    ALK_PEAK_EFFICIENCY,
    ALK_RATED_EFFICIENCY,
    CRF,
    EQUIPMENT_COSTS,
    HB_MWH_PER_T_NH3,
    PROJECT_YEARS,
    ModelSettings,
)
from .design import build_design_model
from .errors import SolverFailure
from .renewables import HourlyInputs


BOUNDARY_TOLERANCE = 1e-8


@dataclass(frozen=True, slots=True)
class RegionStage:
    iteration: int
    lcoa_usd_t: float
    alk_mw: float
    hb_tph: float
    changed_hours: int | None
    boundary_tie_hours: int
    two_cycle_hours: int
    region_counts: tuple[int, ...]
    minimum_hb_load: float
    maximum_hb_load: float
    maximum_curve_power_gap_mw: float | None


@dataclass(frozen=True, slots=True)
class RegionExperimentResult:
    stages: tuple[RegionStage, ...]
    region_history: tuple[tuple[int, ...], ...]
    converged: bool
    model: pyo.ConcreteModel


def classify_production_fraction(
    production_fraction: float, minimum_load: float, previous_region: int | None,
) -> tuple[int, bool]:
    """OR 경계에서만 이전 구간을 유지하고 그 밖에서는 새 q로 재분류한다."""
    points = hb_region_points(minimum_load)
    for boundary_index in range(1, len(points) - 1):
        boundary = hb_production_fraction(points[boundary_index])
        if isclose(production_fraction, boundary, rel_tol=0, abs_tol=BOUNDARY_TOLERANCE):
            if previous_region in (boundary_index - 1, boundary_index):
                return previous_region, True
    return hb_region_for_production(production_fraction, minimum_load), False


def _classify_model(
    model: pyo.ConcreteModel, settings: ModelSettings,
    previous_regions: tuple[int, ...] | None,
) -> tuple[tuple[int, ...], int]:
    hb_capacity = pyo.value(model.hb_tph)
    classifications = tuple(
        classify_production_fraction(
            pyo.value(model.nh3[t]) / hb_capacity,
            settings.hb_minimum_fraction,
            None if previous_regions is None else previous_regions[t],
        ) for t in model.T
    )
    return tuple(region for region, _ in classifications), sum(
        is_boundary for _, is_boundary in classifications
    )


def _classify_constant_efficiency_model(
    model: pyo.ConcreteModel, settings: ModelSettings,
) -> tuple[int, ...]:
    """정효율 LP의 OR은 생산율이 아닌 실제 전력부하 f로 결정한다.

    초기 LP에서는 q=f이지만, Eq. (15)의 비선형 q(f) 경계는 아직
    적용되지 않았다. 따라서 80% 부하 경계는 q(0.8)가 아닌 f=0.8이다.
    """
    points = hb_region_points(settings.hb_minimum_fraction)
    rated_power = HB_MWH_PER_T_NH3 * pyo.value(model.hb_tph)
    return tuple(
        next(
            index for index in range(len(points) - 1)
            if pyo.value(model.hb_power[t]) / rated_power <= points[index + 1]
            + BOUNDARY_TOLERANCE
        )
        for t in model.T
    )


def _solve(
    inputs: HourlyInputs, settings: ModelSettings, regions: tuple[int, ...] | None,
    time_limit: float,
) -> pyo.ConcreteModel:
    model = build_design_model(inputs, settings, regions)
    solver = pyo.SolverFactory("appsi_highs")
    solver.options["time_limit"] = time_limit
    if settings.alk_replacement_milp:
        # 논문 Eq. (22)의 연도별 교체 여부가 이진변수이므로 MIP로 푼다.
        # 정수해의 상대 최적성 간격은 0.1%로 둔다.
        solver.options["mip_rel_gap"] = 0.001
    else:
        solver.options["solver"] = "ipm"
    result = solver.solve(model, load_solutions=False)
    if result.solver.termination_condition != pyo.TerminationCondition.optimal:
        raise SolverFailure(
            f"{result.solver.termination_condition}: "
            f"{result.solver.termination_message}"
        )
    model.solutions.load_from(result)
    return model


def _stage(
    iteration: int, model: pyo.ConcreteModel, inputs: HourlyInputs,
    current_regions: tuple[int, ...], changed_hours: int | None,
    boundary_tie_hours: int, two_cycle_hours: int,
    settings: ModelSettings,
) -> RegionStage:
    hb_capacity = pyo.value(model.hb_tph)
    rated_power = HB_MWH_PER_T_NH3 * hb_capacity
    loads = tuple(pyo.value(model.hb_power[t]) / rated_power for t in model.T)
    gap = None if iteration == 0 else max(
        abs(
            pyo.value(model.hb_power[t])
            - rated_power * hb_load_fraction(pyo.value(model.nh3[t]) / hb_capacity)
        ) for t in model.T
    )
    region_count = len(hb_region_points(settings.hb_minimum_fraction)) - 1
    return RegionStage(
        iteration=iteration,
        lcoa_usd_t=pyo.value(model.annual_cost) / inputs.annual_ammonia_t,
        alk_mw=pyo.value(model.alk_mw),
        hb_tph=hb_capacity,
        changed_hours=changed_hours,
        boundary_tie_hours=boundary_tie_hours,
        two_cycle_hours=two_cycle_hours,
        region_counts=tuple(current_regions.count(index) for index in range(region_count)),
        minimum_hb_load=min(loads),
        maximum_hb_load=max(loads),
        maximum_curve_power_gap_mw=gap,
    )


def solve_region_migration_experiment(
    inputs: HourlyInputs, settings: ModelSettings,
    *, refinements: int = 2, time_limit_per_stage: float = 1200,
    stage_callback: Callable[[RegionStage, tuple[int, ...]], None] | None = None,
    resume_stages: tuple[RegionStage, ...] | None = None,
    resume_region_history: tuple[tuple[int, ...], ...] | None = None,
) -> RegionExperimentResult:
    """정효율 초기해 뒤 할선 배정을 갱신하며 OR 전이 수를 기록한다.

    원 논문 Sec. 3.8의 초기 정효율 LP와 Eq. (15) 구간별 할선은 유지한다.
    이 실험은 Eq. (15)에 붙인 OR별 생산량 제약을 제거한다. Eq. (22)의
    전해조 교체 MILP는 전달된 설정에 따라 켜거나 끈다. 전력부하의
    60~100% 범위는 유지한다.
    저장된 단계와 OR 이력을 전달하면 마지막 OR에서 다음 단계를 시작한다.
    refinements는 재개 시에도 0차 이후의 총 반복 횟수다.
    """
    if not settings.part_load_efficiency or settings.fixed_hb_tph is not None:
        raise SolverFailure("실험에는 가변 HB와 부분부하 효율 설정이 필요합니다")
    common = settings
    if settings.alk_replacement_milp:
        # 논문 Eq. (22)의 용량×이진변수 선형화에는 유한한 Big-M이 필요하다.
        # 정효율 예비 LP의 실행가능해 비용으로 그 상한을 계산한다.
        # 예비 LP는 0차 MILP 및 1·2차 부분부하 MILP 횟수에 포함하지 않는다.
        preparation = _solve(
            inputs,
            replace(
                settings, part_load_efficiency=False,
                alk_replacement_milp=False,
                alk_replacement_years=(), alk_capacity_upper_bound_mw=None,
            ),
            None, time_limit_per_stage,
        )
        # Eq. (22)의 가능한 최대 교체횟수에 해당하는 비용을 LP 비용에
        # 더하면, 정효율 MILP에서 실행가능한 연간 비용의 상한이 된다.
        # 이를 ALK 1 MW당 연간 CAPEX+FOM으로 나눠 Big-M의 유한 상한을
        # 만든다. 부분부하 해에도 적용되므로 결과에서 상한 여유를 확인한다.
        maximum_replacements = ceil(
            PROJECT_YEARS * inputs.hours * ALK_PEAK_EFFICIENCY
            / (ALK_RATED_EFFICIENCY * settings.alk_useful_hours)
        )
        alk_cost = EQUIPMENT_COSTS["alk_mw"]
        feasible_annual_cost = pyo.value(preparation.annual_cost) + (
            CRF * maximum_replacements * 0.4 * alk_cost.capex_usd_per_unit
            * pyo.value(preparation.alk_mw)
        )
        capacity_bound = feasible_annual_cost / (
            alk_cost.capex_usd_per_unit
            * (CRF + alk_cost.annual_om_fraction)
        )
        common = replace(settings, alk_capacity_upper_bound_mw=capacity_bound)
    if (resume_stages is None) != (resume_region_history is None):
        raise ValueError("재개할 때는 단계와 OR 이력을 함께 전달해야 합니다")
    if resume_stages is None:
        # 0차는 정효율 Eq. (9), (13)와 교체 Eq. (22)를 함께 푼 MILP다.
        # 1차부터는 HB Eq. (15)의 OR별 선형식만 추가한다. ALK는 모든
        # 단계에서 Eq. (9)의 정효율이며, 계통 설정도 그대로 유지한다.
        initial = _solve(
            inputs, replace(common, part_load_efficiency=False), None,
            time_limit_per_stage,
        )
        regions = _classify_constant_efficiency_model(initial, common)
        history = [regions]
        stages = [_stage(0, initial, inputs, regions, None, 0, 0, common)]
        print(
            f"initial_{'milp' if common.alk_replacement_milp else 'lp'}: "
            f"LCOA={stages[0].lcoa_usd_t:.3f} USD/t, "
            f"regions={stages[0].region_counts}", flush=True,
        )
        if stage_callback is not None:
            stage_callback(stages[0], regions)
        current = initial
        first_iteration = 1
    else:
        if resume_region_history is None or len(resume_stages) != len(resume_region_history):
            raise ValueError("저장된 단계와 OR 이력의 길이가 일치해야 합니다")
        if any(stage.iteration != index for index, stage in enumerate(resume_stages)):
            raise ValueError("저장된 단계 번호가 연속적이지 않습니다")
        if any(len(regions) != inputs.hours for regions in resume_region_history):
            raise ValueError("저장된 OR 이력의 시간 수가 입력과 다릅니다")
        if refinements <= resume_stages[-1].iteration:
            raise ValueError("총 반복 횟수는 마지막 저장 단계보다 커야 합니다")
        history = list(resume_region_history)
        stages = list(resume_stages)
        regions = history[-1]
        current = None
        first_iteration = stages[-1].iteration + 1
    for iteration in range(first_iteration, refinements + 1):
        current = _solve(inputs, common, regions, time_limit_per_stage)
        updated, boundary_ties = _classify_model(current, common, regions)
        changed = sum(before != after for before, after in zip(regions, updated, strict=True))
        two_cycle = 0 if iteration == 1 else sum(
            before != after and after == two_back
            for two_back, before, after in zip(
                history[-2], regions, updated, strict=True
            )
        )
        stage = _stage(
            iteration, current, inputs, updated, changed, boundary_ties,
            two_cycle, common,
        )
        stages.append(stage)
        history.append(updated)
        print(
            f"refinement_{iteration}: LCOA={stage.lcoa_usd_t:.3f} USD/t, "
            f"changed_hours={changed}, boundary_ties={boundary_ties}, "
            f"two_cycle_hours={two_cycle}, regions={stage.region_counts}, "
            f"HB_load={stage.minimum_hb_load:.6f}..{stage.maximum_hb_load:.6f}",
            flush=True,
        )
        if stage_callback is not None:
            stage_callback(stage, updated)
        regions = updated
    return RegionExperimentResult(tuple(stages), tuple(history), changed == 0, current)
