# 모듈형 암모니아 최적화 코드 사용 가이드

이 가이드는 `run_cambridge_argentina_modular.py`가 읽는 입력, 최적화에서 결정하는 값, 결과 파일을 설명한다. 실행 명령은 저장소의 최상위 폴더에서 입력한다.

## 실행

```powershell
uv sync
uv run python run_cambridge_argentina_modular.py
uv run python -m tests.test_modular_model
```

첫 번째 명령은 `pyproject.toml`에 지정된 패키지를 설치한다. 두 번째 명령은 HiGHS로 연간 설비용량과 시간별 운전을 최적화하고, 세 번째 명령은 모델의 기본 검사를 실행한다. 최적화가 끝나면 `results/cambridge_2013_argentina_modular/summary.json`과 `hourly.csv`가 생성된다. 최적해를 얻지 못하거나 전해조의 25년 누적 등가 전부하시간이 80,000시간 이상이면 실행은 오류와 함께 종료된다.

## 입력과 실행 흐름

1. [`run_cambridge_argentina_modular.py`](../run_cambridge_argentina_modular.py)의 `main()`이 입력 경로와 `ModelSettings`를 정한다.
2. [`green_ammonia/renewables.py`](../green_ammonia/renewables.py)의 `cambridge_2013_inputs()`가 `data/benchmark_cambridge/`의 PVGIS 태양광 JSON과 NEWA 풍력 NetCDF를 읽어 `HourlyInputs`를 만든다.
3. [`green_ammonia/design.py`](../green_ammonia/design.py)의 `build_design_model()`이 설비별 변수와 제약, 전력수지, 연간 비용식을 한 Pyomo 모델에 모은다.
4. HiGHS가 연간 비용이 최소인 설비용량과 매시간의 생산·저장·충방전량을 구한다. 실행 파일이 결과를 JSON과 CSV로 저장한다.

PVGIS의 `P`는 W/kWp 단위 출력이며, 코드는 이를 1,000으로 나눠 태양광 용량계수로 사용한다. NEWA의 `WS10`은 30분 간격 풍속이다. 연속한 두 값을 평균해 시간별 풍속을 만들고, 100 m 높이로 환산한 뒤 풍력터빈 출력곡선(절입 3, 정격 13, 차단 25 m/s)을 적용한다. 입력은 각각 8,760시간의 태양광 용량계수 `solar_cf`, 풍력 용량계수 `wind_cf`, 암모니아 출하량 `delivery_tph`로 구성된다. 출하량은 매시간 230/24 t이다.

## 현재 실행의 설정과 단위

설비 가격, 에너지 원단위, 할인율은 [`green_ammonia/assumptions.py`](../green_ammonia/assumptions.py)에 있다. 다음 값은 실행 파일의 `ModelSettings(...)`에서 직접 지정하거나 기본값으로 적용된다.

| 설정 | 현재 값 | 코드에서 하는 일 |
|---|---:|---|
| `solar_delivery_factor` | 1.0 | PVGIS 출력에 곱하는 계수. 입력 `P`를 이미 계산된 설비 출력으로 사용한다. |
| `wind_delivery_factor` | 0.851 | 풍력 출력곡선에서 얻은 용량계수에 곱하는 전달계수. |
| `grid_allowed` | `False` | 계통 설비용량 `grid_mw`를 0으로 고정한다. |
| `fixed_hb_tph` | 230/24 t/h | 하버보슈 설비용량과 매시간 암모니아 생산량을 고정한다. 이 모드에서 암모니아 탱크용량은 0이다. |
| `nitrogen_storage_enabled` | `True` | 질소 탱크의 용량과 시간별 재고를 최적화한다. |
| `battery_round_trip_efficiency` | 0.90 | 배터리 충전·방전 양쪽에 왕복효율의 제곱근을 적용한다. |
| `alk_replacement_years` | 빈 튜플 | 현재 비용식에는 전해조 교체비를 더하지 않는다. 풀이 후 누적 가동시간 조건을 확인한다. |

설비용량은 전력 설비의 경우 MW, 배터리 에너지용량은 MWh, 물질 탱크용량은 t, ASU·HB 용량은 t/h이다. 시간 간격이 정확히 1시간이므로 시간별 전력 MW의 숫자는 그 시간에 사용한 에너지 MWh의 숫자와 같다. 비용은 USD, LCOA는 USD/t NH₃이다.

## 모델의 주요 식

Pyomo에서 `Var`는 최적화가 결정하는 값, `Constraint`는 반드시 지켜야 하는 식, `Expression`은 변수로 계산한 값, `Objective`는 최소화할 값이다. `model.T`는 0부터 8759까지의 시간 인덱스다. 설비용량 변수와 시간별 운전 변수는 모두 0 이상이다.

| 모듈 | 핵심 변수·제약 | 의미 |
|---|---|---|
| [`hydrogen.py`](../green_ammonia/hydrogen.py) | `alk_power`, `h2_production`, `h2_balance` | 수소 생산량(t/h) = 전해조 소비전력(MW) ÷ (39/0.682 MWh/t). 수소 재고 변화 = 생산량 − `(6/34) × nh3`. |
| [`nitrogen.py`](../green_ammonia/nitrogen.py) | `n2_production`, `n2_balance` | 질소 재고 변화 = ASU 생산량 − `(28/34) × nh3`. |
| [`ammonia.py`](../green_ammonia/ammonia.py) | `nh3`, `nh3_balance` | 암모니아 재고 변화 = HB 생산량 − 입력의 출하량. 고정 HB 실행에서는 `nh3[t]`가 매시간 230/24 t/h로 고정된다. |
| [`battery.py`](../green_ammonia/battery.py) | `bess_charge`, `bess_discharge`, `bess_balance` | `SOC[t] = SOC[t−1] + √η × charge[t] − discharge[t]/√η`. 충·방전 출력과 SOC는 각각 설치용량 이하이다. |
| [`electricity.py`](../green_ammonia/electricity.py) | `power_balance`, `curtail` | 태양광 + 풍력 + 계통 + 배터리 방전 = 전해조·압축기·RO·ASU·HB 소비 + 배터리 충전 + 출력제한. |
| [`economics.py`](../green_ammonia/economics.py) | `annual_cost`, `objective` | 초기 투자비와 교체비의 현재가치를 연간 환산하고 고정 운영비·계통 비용을 더해 최소화한다. |

수소·질소의 암모니아 1 t당 소비량 `6/34`, `28/34`는 `N₂ + 3 H₂ → 2 NH₃`의 질량비다. 각 저장 수지에서 첫 시간 직전의 재고는 마지막 시간의 재고로 연결한다. 따라서 저장량은 한 해를 순환하며 끝에서 다음 해로 이어진다.

비용식은 `annual_cost = CRF × (초기 CAPEX + 배터리 교체비 현재가치 + 전해조 교체비 현재가치) + 연간 고정 O&M + 연간 계통 비용`이다. 할인율은 7%, 사업기간은 25년이며, 배터리 교체비는 8·16·24년을 할인해 합산한다. `objective`는 수치 규모를 줄이기 위해 `annual_cost / 1,000,000`을 최소화한다. 연간 암모니아 출하량이 입력에서 고정되므로 이 최적해는 `LCOA = annual_cost / annual_ammonia_t`의 최소해와 같다.

## 결과 파일 읽기

- `summary.json`: `lcoa_usd_t`, `annual_cost_usd`, `annual_cost_breakdown_usd`, `capacities`, `settings`, 전해조 등가 전부하시간, 풀이 상태와 각 수지의 최대 오차가 들어 있다. `capacities`에서 설비의 최적 설치용량을 확인한다.
- `hourly.csv`: 각 시간의 용량계수·발전 가능 전력·수소/질소/암모니아 생산량·물질 재고·배터리 SOC·계통 전력·출력제한을 기록한다. 열 이름의 `_mw`, `_mwh`, `_tph`, `_t`는 각각 MW, MWh, t/h, t를 뜻한다.

선형계획에는 같은 시간의 배터리 충전과 방전을 금지하는 제약이 없다. [`battery.py`](../green_ammonia/battery.py)의 `physical_dispatch()`는 저장할 CSV에 한해 동시 운전을 같은 SOC 변화의 순수 충전 또는 방전으로 바꾸고, 그 차이를 출력제한에 더한다. `summary.json`의 `simultaneous_battery_charge_discharge_hours`는 후처리 전 해를 기준으로 세며, 설비용량과 LCOA도 후처리 전 최적해의 값이다.

이 실행은 전체 8,760시간의 재생에너지 값을 한 번에 알고 푸는 정효율 선형계획이다. 전해조의 수소 생산 효율과 HB의 전력 원단위는 운전 부하에 따라 변하지 않는다. 이 범위를 알고 있어야 `summary.json`의 비용과 `hourly.csv`의 운전을 올바르게 해석할 수 있다.
