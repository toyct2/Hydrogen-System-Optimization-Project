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


def build_design_model(
    inputs: HourlyInputs, settings: ModelSettings,
    hb_regions: tuple[int, ...] | None = None,
) -> pyo.ConcreteModel:
    """설비용량과 시간별 운전을 동시에 정하는 LP/MILP 문제를 조립한다.

    변수는 `Var`, 물리 법칙은 `Constraint`, 연간 비용은 `Objective`다.
    각 부품 모듈은 자신의 변수와 제약만 소유한다. 마지막 전력수지가
    모든 부품을 연결하며, 이 조립 순서가 부품 간 의존관계를 보여준다.
    """
    # 분모가 0이면 논문 Eq. (28)의 LCOA가 정의되지 않는다.
    if inputs.annual_ammonia_t <= 0:
        raise InvalidModelInput("연간 암모니아 출하량은 양수여야 합니다")
    # 고정 HB 생산량의 연간 합은 저장 수지 Eq. (18)의 순환 조건상
    # 연간 출하량과 같아야 한다. 다르면 암모니아 재고가 해마다 증가/감소한다.
    if settings.fixed_hb_tph is not None and abs(
        settings.fixed_hb_tph * inputs.hours - inputs.annual_ammonia_t
    ) > 1e-5:
        raise InvalidModelInput("고정 HB 생산량과 연간 출하량의 합이 다릅니다")
    model = pyo.ConcreteModel()
    # Pyomo RangeSet은 0부터 마지막 시간까지의 제약을 반복 생성한다.
    # 논문은 8,736시간(52주)을 쓰지만 이 입력 자료에는 8,760시간이 있다.
    model.T = pyo.RangeSet(0, inputs.hours - 1)
    add_ammonia_system(model, inputs, settings, hb_regions)
    add_hydrogen_system(model, settings)
    add_nitrogen_system(model, settings.nitrogen_storage_enabled)
    add_battery(model, settings.battery_round_trip_efficiency)
    # 마지막 전력수지 Eq. (1)이 앞에서 만든 모든 공정의 전력 수요를 연결한다.
    add_electricity_bus(model, inputs, settings)
    add_annual_cost(model, settings)
    return model
