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
    wind_100m = half_hourly.reshape(8760, 2).mean(axis=1) * 10**0.143
    power = np.where(
        (wind_100m > 3) & (wind_100m <= 13),
        (wind_100m**3 - 3**3) / (13**3 - 3**3),
        np.where((wind_100m > 13) & (wind_100m <= 25), 1.0, 0.0),
    )
    return tuple(float(value) for value in power)


def cambridge_2013_inputs(root: Path) -> HourlyInputs:
    solar = read_pvgis_solar(root / "pvgis_35.5_-0.5_2013_v52.json")
    wind = read_newa_wind(root / "newa_35.5_-0.5_2013.nc")
    return HourlyInputs(solar, wind, (230 / 24,) * len(solar))
