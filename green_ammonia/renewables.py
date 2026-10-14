"""공개 PVGIS/NEWA 자료를 1시간 간격 발전 가능 비율로 변환한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from .errors import InvalidModelInput


@dataclass(frozen=True, slots=True)
class HourlyInputs:
    """1시간 시간축의 PV·풍력 용량계수와 NH3 출하량.

    용량계수 0.4는 설치용량 1 MW에서 그 시간에 0.4 MWh를 얻는다는 뜻이다.
    delivery_tph는 그 시간에 공장 밖으로 나가야 하는 NH3 톤수다.
    """

    solar_cf: tuple[float, ...]
    wind_cf: tuple[float, ...]
    delivery_tph: tuple[float, ...]

    # __post_init__은 dataclass 생성 직후 실행되어 세 시계열의 길이·범위를 확인한다.
    # 논문 Eq. (1)의 발전량과 Eq. (18)의 출하량을 같은 시간축에 놓기 위한 검사다.
    def __post_init__(self) -> None:
        hours = len(self.solar_cf)
        if hours == 0 or len(self.wind_cf) != hours or len(self.delivery_tph) != hours:
            raise InvalidModelInput("태양광·풍력·출하량은 같은 길이의 비어 있지 않은 시간열이어야 합니다")
        if any(not isfinite(cf) or not 0 <= cf <= 1 for cf in self.solar_cf + self.wind_cf):
            raise InvalidModelInput("발전 용량계수는 0과 1 사이여야 합니다")
        if any(not isfinite(amount) or amount < 0 for amount in self.delivery_tph):
            raise InvalidModelInput("출하량은 음수가 될 수 없습니다")

    @property
    def hours(self) -> int:
        return len(self.solar_cf)

    @property
    def annual_ammonia_t(self) -> float:
        return sum(self.delivery_tph)


def read_pvgis_solar(path: Path) -> tuple[float, ...]:
    """PVGIS 시간별 `P`(W/kWp)를 MW/MWp 용량계수로 읽는다."""
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    hourly = payload["outputs"]["hourly"]
    # P는 정격 1 kWp 태양광 설비의 W 출력이며 시스템 손실이 이미 반영되어 있다.
    # 1,000으로 나누면 설치 1 MWp당 MW 출력(용량계수)과 수치가 같아진다.
    # 이는 논문 Eq. (1)의 ES(i) 입력을 만드는 전처리이며 논문의 별도 번호식은 아니다.
    return tuple(float(row["P"]) / 1000 for row in hourly)


def read_newa_wind(path: Path) -> tuple[float, ...]:
    """저자 공개 MATLAB 전처리와 같은 10→100 m 풍속·출력곡선을 쓴다.

    NEWA WS10은 30분 간격이다. 두 표본을 평균해 1시간 풍속을 만들고,
    풍속 세제곱 출력곡선의 3/13/25 m/s 절입·정격·차단점을 적용한다.
    여기서는 0.851 손실을 곱하지 않는다. 그 손실은 전력수지에서 적용한다.
    """
    with netcdf_file(path, "r", mmap=False) as dataset:
        half_hourly = np.asarray(dataset.variables["WS10"][:], dtype=float)
    if len(half_hourly) != 17_520:
        raise InvalidModelInput("NEWA 파일에는 2013년 30분 표본 17,520개가 필요합니다")
    # reshape(8760, 2)는 연속된 30분 표본 두 개를 한 시간으로 묶는다.
    # 10**0.143은 10 m 풍속을 100 m 허브 높이로 옮기는 멱법칙 계수다.
    # 이 곡선은 Cambridge 공개 데이터의 전처리를 따른다. Argentina 논문 Eq. (1)은
    # 이미 주어진 풍력 출력 EW(i)을 받으므로 이 전처리의 식 번호는 없다.
    wind_100m = half_hourly.reshape(8760, 2).mean(axis=1) * 10**0.143
    # np.where는 각 시간 풍속에 세 구간을 한꺼번에 적용한다:
    # 3 m/s 이하 또는 25 m/s 초과면 0, 3-13은 풍속 세제곱으로 상승,
    # 13-25는 정격 출력 1.0이다. 반환값에는 0.851 전달계수를 곱하지 않는다.
    power = np.where(
        (wind_100m > 3) & (wind_100m <= 13),
        (wind_100m**3 - 3**3) / (13**3 - 3**3),
        np.where((wind_100m > 13) & (wind_100m <= 25), 1.0, 0.0),
    )
    return tuple(float(value) for value in power)


def cambridge_2013_inputs(root: Path) -> HourlyInputs:
    solar = read_pvgis_solar(root / "pvgis_35.5_-0.5_2013_v52.json")
    wind = read_newa_wind(root / "newa_35.5_-0.5_2013.nc")
    # 튜플 (230 / 24,)를 시간 수만큼 반복하면 매시간 같은 t/h 출하량이 된다.
    # 논문 Eq. (21)의 14일 주기·48시간 선적 대신 일정 출하를 입력하는 설정이다.
    return HourlyInputs(solar, wind, (230 / 24,) * len(solar))
