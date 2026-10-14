"""그린 암모니아 모델에 사용하는 숫자와 단위.

설비 가격의 근거는 Schmidhalter et al. (2025), Table 2이다. 아래에서
정격 출력은 MW, 저장량은 MWh 또는 t, 비용은 USD로 통일한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Final

from .errors import InvalidModelInput


# 설비별 단가와 O&M 비율을 함께 묶는다. frozen=True라 생성 뒤 값을
# 바꿀 수 없고, slots=True라 정해진 필드 외의 속성을 추가할 수 없다.
@dataclass(frozen=True, slots=True)
class EquipmentCost:
    capex_usd_per_unit: float
    annual_om_fraction: float


EQUIPMENT_COSTS: Final[dict[str, EquipmentCost]] = {
    # Schmidhalter et al. (2025) Table 2의 설비별 CAPEX와 연간 O&M 비율.
    # 논문 Eq. (26)은 CAPEX, Eq. (27)은 고정 OPEX를 설비용량별로 합산한다.
    # 아래 BESS는 출력(MW)과 저장량(MWh)을 별도 비용 항목으로 다룬다.
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
# 논문 Eq. (25)의 연도별 할인계수를 일정 연간비용으로 환산한 자본회수계수.
# 이 값은 Eq. (28)의 현재가치 비율을 연간 비용 / 연간 생산량 형태로 바꿀 때 사용한다.
CRF: Final = DISCOUNT_RATE / (1 - (1 + DISCOUNT_RATE) ** -PROJECT_YEARS)

# 논문 Sec. 3.4의 HB 투입물 화학양론: N2 + 3 H2 -> 2 NH3.
# 질량 34 t의 NH3에 H2 6 t과 N2 28 t이 필요하다. 독립된 번호식은 아니다.
H2_T_PER_NH3_T: Final = 6 / 34
N2_T_PER_NH3_T: Final = 28 / 34

# 논문 Eq. (9)의 정효율 전해조: H2 생산량 = 전해조 전력 × 0.682 / 39.
# 코드는 나눗셈에 쓸 원단위 39/0.682 MWh/t H2로 저장한다(Table 2).
ALK_MWH_PER_T_H2: Final = 39 / 0.682
ALK_RATED_EFFICIENCY: Final = 0.682
# 다음 압축·RO 원단위는 논문 Sec. 3.4와 Table 2의 공정 가정이다.
# 각 유량에 곱해 MW를 계산하며, 별도의 번호식으로 제시되지는 않는다.
H2_COMP_MWH_PER_T_H2: Final = 1.37
RO_MWH_PER_T_H2: Final = 0.060  # 12 m3/t H2 × 5 kWh/m3.
ASU_MWH_PER_T_N2: Final = 0.148
N2_COMP_MWH_PER_T_N2: Final = 0.098
# HB 원단위 0.311은 논문 Eq. (13)의 정효율 근사에 사용한다.
HB_MWH_PER_T_NH3: Final = 0.311
# Fig. 2의 최대 효율 약 0.77은 Eq. (22) 교체 MILP의 보수적 Big-M
# 상한 계산에만 사용한다. 시간별 전해조 생산식은 Eq. (9)의 0.682다.
ALK_PEAK_EFFICIENCY: Final = 0.77
# Eq. (14)와 Fig. 5의 HB 부분부하 인자.
HB_PART_LOAD_ALPHA: Final = 0.50


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """설비 운전과 발전 자료에 적용할 계수를 지정한다.

    실행 파일은 PVGIS `P`에 손실이 포함된 점을 반영해
    solar_delivery_factor=1을 지정한다. 풍력 0.851은
    유지보수·후류·송전 손실을 나타내며 NEWA 출력에 곱한다.
    """

    # 논문 Eq. (1)의 원 풍력·태양광 출력을 버스에 도달하는 전력으로 환산한다.
    # 실행 파일에서는 PVGIS P에 이미 손실이 반영되어 있어 태양광 계수를 1로 덮어쓴다.
    wind_delivery_factor: float = 0.851
    solar_delivery_factor: float = 0.85
    # 논문 Eq. (19)는 배터리 손실을 방전측에 둔다.
    # 여기의 0.90은 논문 Table 2에 명시되지 않은 별도 왕복효율 가정이다.
    battery_round_trip_efficiency: float = 0.90
    grid_allowed: bool = True
    nitrogen_storage_enabled: bool = True
    # None이면 HB 용량·시간별 생산량이 변수이고, 숫자이면 둘 다 고정한다.
    fixed_hb_tph: float | None = None
    part_load_efficiency: bool = False
    # part_load_efficiency는 HB의 1·2차 재선형화에만 적용된다.
    # 전해조는 모든 단계에서 논문 Eq. (9)의 정효율을 사용한다.
    hb_minimum_fraction: float = 0.60
    hb_ramp_up_fraction: float = 0.02
    hb_ramp_down_fraction: float = 0.20
    # 논문 Eq. (22)는 80,000 등가 전부하시간에 따른 교체 시점을 조건식으로 정한다.
    # 이 LP는 교체 연도를 최적화하지 않고 외부에서 전달된 연도만 비용에 넣는다.
    alk_replacement_years: tuple[int, ...] = ()
    # Eq. (22)의 교체 시점을 모델 내부의 이진변수로 결정한다.
    # 유한 상한은 용량×교체여부의 정확한 MILP 선형화에 필요하다.
    alk_replacement_milp: bool = False
    alk_capacity_upper_bound_mw: float | None = None
    alk_useful_hours: float = ALK_USEFUL_HOURS

    # dataclass 생성 직후 실행되는 검사. 범위를 벗어난 설정을 모델
    # 조립 이전에 거절해 음의 효율·교체 연도 같은 잘못된 입력을 막는다.
    def __post_init__(self) -> None:
        if not 0 <= self.wind_delivery_factor <= 1 or not 0 <= self.solar_delivery_factor <= 1:
            raise InvalidModelInput("태양광·풍력 전달계수는 0과 1 사이여야 합니다")
        if not 0 < self.battery_round_trip_efficiency <= 1:
            raise InvalidModelInput("배터리 왕복효율은 0보다 크고 1 이하여야 합니다")
        if self.fixed_hb_tph is not None and not isfinite(self.fixed_hb_tph):
            raise InvalidModelInput("HB 고정 생산량은 유한한 숫자여야 합니다")
        if self.fixed_hb_tph is not None and self.fixed_hb_tph < 0:
            raise InvalidModelInput("HB 고정 생산량은 음수가 될 수 없습니다")
        if self.part_load_efficiency and self.fixed_hb_tph is not None:
            raise InvalidModelInput("부분부하 시나리오에서는 HB 생산량이 가변이어야 합니다")
        if not 0 <= self.hb_minimum_fraction <= 1:
            raise InvalidModelInput("HB 최소 부하율은 0과 1 사이여야 합니다")
        if self.hb_ramp_up_fraction < 0 or self.hb_ramp_down_fraction < 0:
            raise InvalidModelInput("HB 램프 한도는 음수가 될 수 없습니다")
        if any(year < 1 or year > PROJECT_YEARS for year in self.alk_replacement_years):
            raise InvalidModelInput("전해조 교체 연도는 프로젝트 기간 안에 있어야 합니다")
        if self.alk_replacement_milp and self.alk_replacement_years:
            raise InvalidModelInput("MILP 교체와 지정된 교체 연도는 동시에 사용할 수 없습니다")
        # 단계적 풀이가 예비 정효율 LP로 용량 상한을 계산하므로 여기서는
        # None을 허용한다. 실제 모델 조립 시 replacement.py가 유한 상한을 요구한다.
        if self.alk_replacement_milp and self.alk_capacity_upper_bound_mw is not None and (
            not isfinite(self.alk_capacity_upper_bound_mw)
            or self.alk_capacity_upper_bound_mw <= 0
        ):
            raise InvalidModelInput("MILP 교체의 전해조 용량 상한은 양의 유한값이어야 합니다")
        if not isfinite(self.alk_useful_hours) or self.alk_useful_hours <= 0:
            raise InvalidModelInput("전해조 유효수명은 양의 유한 시간이어야 합니다")
