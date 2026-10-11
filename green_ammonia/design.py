from __future__ import annotations

import pyomo.environ as pyo

from .ammonia import add_ammonia_system
from .assumptions import ModelSettings
from .battery import add_battery
from .economics import add_annual_cost
from .electricity import add_electricity_bus
from .errors import InvalidModelInput
from .hydrogen import add_hydrogen_system
from .nitrogen import add_nitrogen_system
from .renewables import HourlyInputs


def build_design_model(inputs: HourlyInputs, settings: ModelSettings) -> pyo.ConcreteModel:
    """설비용량과 시간별 운전을 동시에 정하는 선형 최적화 문제를 조립한다.

    변수는 `Var`, 물리 법칙은 `Constraint`, 연간 비용은 `Objective`다.
    각 부품 모듈은 자신의 변수와 제약만 소유한다. 마지막 전력수지가
    모든 부품을 연결하며, 이 조립 순서가 부품 간 의존관계를 보여준다.
    """
    if inputs.annual_ammonia_t <= 0:
        raise InvalidModelInput("연간 암모니아 출하량은 양수여야 합니다")
    if settings.fixed_hb_tph is not None and abs(
        settings.fixed_hb_tph * inputs.hours - inputs.annual_ammonia_t
    ) > 1e-5:
        raise InvalidModelInput("고정 HB 생산량과 연간 출하량의 합이 다릅니다")
    model = pyo.ConcreteModel()
    model.T = pyo.RangeSet(0, inputs.hours - 1)
    add_ammonia_system(model, inputs, settings)
    add_hydrogen_system(model)
    add_nitrogen_system(model, settings.nitrogen_storage_enabled)
    add_battery(model, settings.battery_round_trip_efficiency)
    add_electricity_bus(model, inputs, settings)
    add_annual_cost(model, settings)
    return model
