from __future__ import annotations

import csv
import json
from pathlib import Path

import pyomo.environ as pyo

from green_ammonia.assumptions import ALK_USEFUL_HOURS, CRF, EQUIPMENT_COSTS, ModelSettings, PROJECT_YEARS
from green_ammonia.battery import physical_dispatch
from green_ammonia.design import build_design_model
from green_ammonia.errors import SolverFailure
from green_ammonia.renewables import cambridge_2013_inputs

DATA = Path("data/benchmark_cambridge")
OUTPUT = Path("results/cambridge_2013_argentina_modular")


def main() -> None:
    inputs = cambridge_2013_inputs(DATA)
    settings = ModelSettings(
        solar_delivery_factor=1.0,
        grid_allowed=False,
        fixed_hb_tph=230 / 24,
        alk_replacement_years=(),
    )
    model = build_design_model(inputs, settings)
    solver = pyo.SolverFactory("appsi_highs")
    solver.options["time_limit"] = 600
    solution = solver.solve(model)
    status = solution.solver.termination_condition
    if status != pyo.TerminationCondition.optimal:
        raise SolverFailure(str(status))

    annual_alk_full_load_hours = sum(pyo.value(model.alk_power[t]) for t in model.T) / pyo.value(model.alk_mw)
    if annual_alk_full_load_hours * PROJECT_YEARS >= ALK_USEFUL_HOURS:
        raise SolverFailure("전해조가 25년 안에 80,000 등가 전부하시간에 도달해 교체비 재계산이 필요합니다")

    capacities = {
        name: pyo.value(getattr(model, name)) for name in EQUIPMENT_COSTS
    }
    capacities["grid_mw"] = pyo.value(model.grid_mw)
    annual_cost = pyo.value(model.annual_cost)
    summary = {
        "scenario": "Cambridge 2013 PVGIS/NEWA; Argentina constant-efficiency LP; fixed HB; N2 storage enabled",
        "hours": inputs.hours,
        "annual_ammonia_t": inputs.annual_ammonia_t,
        "annual_cost_usd": annual_cost,
        "annual_alk_equivalent_full_load_hours": annual_alk_full_load_hours,
        "project_alk_equivalent_full_load_hours": annual_alk_full_load_hours * PROJECT_YEARS,
        "lcoa_usd_t": annual_cost / inputs.annual_ammonia_t,
        "annual_cost_breakdown_usd": {
            "initial_capex_annualized": CRF * pyo.value(model.initial_capex),
            "fixed_om": pyo.value(model.fixed_om),
            "battery_replacement_annualized": CRF * pyo.value(model.battery_replacement_pv),
            "alk_replacement_annualized": CRF * pyo.value(model.alk_replacement_pv),
            "grid": pyo.value(model.grid_annual_cost),
        },
        "capacities": capacities,
        "settings": {
            "wind_delivery_factor": settings.wind_delivery_factor,
            "solar_delivery_factor": settings.solar_delivery_factor,
            "battery_round_trip_efficiency": settings.battery_round_trip_efficiency,
            "nitrogen_storage_enabled": settings.nitrogen_storage_enabled,
            "grid_allowed": settings.grid_allowed,
            "fixed_hb_tph": settings.fixed_hb_tph,
            "alk_replacement_years": settings.alk_replacement_years,
            "hb_minimum_fraction": settings.hb_minimum_fraction,
            "hb_ramp_up_fraction": settings.hb_ramp_up_fraction,
            "hb_ramp_down_fraction": settings.hb_ramp_down_fraction,
        },
        "solver_status": str(status),
        "simultaneous_battery_charge_discharge_hours": sum(
            pyo.value(model.bess_charge[t]) > 1e-7
            and pyo.value(model.bess_discharge[t]) > 1e-7
            for t in model.T
        ),
        "max_power_balance_error_mw": max(
            abs(pyo.value(model.power_balance[t].body)) for t in model.T
        ),
        "max_h2_balance_error_t": max(
            abs(pyo.value(model.h2_balance[t].body)) for t in model.T
        ),
        "max_n2_balance_error_t": max(
            abs(pyo.value(model.n2_balance[t].body)) for t in model.T
        ),
        "max_nh3_balance_error_t": max(
            abs(pyo.value(model.nh3_balance[t].body)) for t in model.T
        ),
        "max_battery_balance_error_mwh": max(
            abs(pyo.value(model.bess_balance[t].body)) for t in model.T
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    hourly = []
    for t in model.T:
        battery = physical_dispatch(
            pyo.value(model.bess_charge[t]),
            pyo.value(model.bess_discharge[t]),
            settings.battery_round_trip_efficiency,
        )
        hourly.append((
            t, inputs.solar_cf[t], inputs.wind_cf[t],
            settings.solar_delivery_factor * inputs.solar_cf[t] * capacities["solar_mw"],
            settings.wind_delivery_factor * inputs.wind_cf[t] * capacities["wind_mw"],
            pyo.value(model.alk_power[t]), pyo.value(model.h2_production[t]),
            pyo.value(model.n2_production[t]), pyo.value(model.nh3[t]),
            pyo.value(model.h2_inventory[t]), pyo.value(model.n2_inventory[t]),
            pyo.value(model.nh3_inventory[t]), battery.charge_mw,
            battery.discharge_mw, pyo.value(model.bess_soc[t]),
            pyo.value(model.grid[t]), pyo.value(model.curtail[t]) + battery.extra_curtail_mw,
        ))
    with (OUTPUT / "hourly.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow((
            "hour", "solar_cf", "wind_cf", "solar_available_mw", "wind_available_mw",
            "alk_power_mw", "h2_production_tph",
            "n2_production_tph", "nh3_production_tph", "h2_inventory_t",
            "n2_inventory_t", "nh3_inventory_t", "bess_charge_mw",
            "bess_discharge_mw", "bess_soc_mwh", "grid_mw", "curtail_mw",
        ))
        writer.writerows(hourly)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
