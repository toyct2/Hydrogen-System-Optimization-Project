"""정효율 그린 암모니아 모델에 사용하는 숫자와 단위.

설비 가격의 근거는 Schmidhalter et al. (2025), Table 2이다. 아래에서
정격 출력은 MW, 저장량은 MWh 또는 t, 비용은 USD로 통일한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Final

from .errors import InvalidModelInput


@dataclass(frozen=True, slots=True)
class EquipmentCost:
    capex_usd_per_unit: float
    annual_om_fraction: float


EQUIPMENT_COSTS: Final[dict[str, EquipmentCost]] = {
    "wind_mw": EquipmentCost(1_200_000, 0.020),
    "solar_mw": EquipmentCost(714_000, 0.017),
    "alk_mw": EquipmentCost(714_000, 0.020),
    "bess_mw": EquipmentCost(100_000, 0),
    "bess_mwh": EquipmentCost(200_000, 0),
    "h2_tank_t": EquipmentCost(350_000, 0.020),
    "n2_tank_t": EquipmentCost(25_000, 0.020),
    "nh3_tank_t": EquipmentCost(500, 0.030),
    "hb_tph": EquipmentCost(5_940_000, 0.020),
    "h2_compressor_mw": EquipmentCost(1_036_000, 0.030),
    "n2_compressor_mw": EquipmentCost(932_000, 0.020),
    "asu_tph": EquipmentCost(802_000, 0.050),
    "ro_mw": EquipmentCost(2_260_000, 0.041),
}

DISCOUNT_RATE: Final = 0.07
PROJECT_YEARS: Final = 25
ALK_USEFUL_HOURS: Final = 80_000
CRF: Final = DISCOUNT_RATE / (1 - (1 + DISCOUNT_RATE) ** -PROJECT_YEARS)

# 반응식 N2 + 3 H2 -> 2 NH3: 질량비는 6/34와 28/34이다.
H2_T_PER_NH3_T: Final = 6 / 34
N2_T_PER_NH3_T: Final = 28 / 34

# HHV=39 MWh/t H2, 알칼라인 전해조 정격 효율=68.2% (Table 2, Eq. 9).
ALK_MWH_PER_T_H2: Final = 39 / 0.682
H2_COMP_MWH_PER_T_H2: Final = 1.37
RO_MWH_PER_T_H2: Final = 0.060  # 12 m3/t H2 × 5 kWh/m3.
ASU_MWH_PER_T_N2: Final = 0.148
N2_COMP_MWH_PER_T_N2: Final = 0.098
HB_MWH_PER_T_NH3: Final = 0.311


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """설비 운전과 발전 자료에 적용할 계수를 지정한다.

    실행 파일은 PVGIS `P`에 손실이 포함된 점을 반영해
    solar_delivery_factor=1을 지정한다. 풍력 0.851은
    유지보수·후류·송전 손실을 나타내며 NEWA 출력에 곱한다.
    """

    wind_delivery_factor: float = 0.851
    solar_delivery_factor: float = 0.85
    battery_round_trip_efficiency: float = 0.90
    grid_allowed: bool = True
    nitrogen_storage_enabled: bool = True
    fixed_hb_tph: float | None = None
    hb_minimum_fraction: float = 0.60
    hb_ramp_up_fraction: float = 0.02
    hb_ramp_down_fraction: float = 0.20
    alk_replacement_years: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.wind_delivery_factor <= 1 or not 0 <= self.solar_delivery_factor <= 1:
            raise InvalidModelInput("태양광·풍력 전달계수는 0과 1 사이여야 합니다")
        if not 0 < self.battery_round_trip_efficiency <= 1:
            raise InvalidModelInput("배터리 왕복효율은 0보다 크고 1 이하여야 합니다")
        if self.fixed_hb_tph is not None and not isfinite(self.fixed_hb_tph):
            raise InvalidModelInput("HB 고정 생산량은 유한한 숫자여야 합니다")
        if self.fixed_hb_tph is not None and self.fixed_hb_tph < 0:
            raise InvalidModelInput("HB 고정 생산량은 음수가 될 수 없습니다")
        if not 0 <= self.hb_minimum_fraction <= 1:
            raise InvalidModelInput("HB 최소 부하율은 0과 1 사이여야 합니다")
        if self.hb_ramp_up_fraction < 0 or self.hb_ramp_down_fraction < 0:
            raise InvalidModelInput("HB 램프 한도는 음수가 될 수 없습니다")
        if any(year < 1 or year > PROJECT_YEARS for year in self.alk_replacement_years):
            raise InvalidModelInput("전해조 교체 연도는 프로젝트 기간 안에 있어야 합니다")
