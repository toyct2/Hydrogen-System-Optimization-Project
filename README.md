# 재생에너지 기반 그린 암모니아 설비용량 최적화

2013년 PVGIS 태양광·NEWA 풍력 자료로 연간 83,950 t의 암모니아 생산 설비를 최적화한다. 공정·비용 모델은 [Schmidhalter et al. (2025)](https://doi.org/10.1016/j.ijhydene.2025.03.317)을 바탕으로 한다. 발전 자료의 위치와 연도는 [Smith and Torrente-Murciano (2025)](https://doi.org/10.1038/s44286-025-00207-9)에 맞췄다. 데이터 변환 과정은 [발전 데이터 설명](data/benchmark_cambridge/README.md)에 있다.

## 현재 실행 버전

현재 실행 파일은 `run_hb_region_milp.py` 하나다. 전해조는 논문 식 (9)의 정효율을 사용하고, 25년 사업기간의 교체 시점과 비용은 식 (22)에 따라 MILP로 결정한다. 계통 전력 구매는 허용한다. 하버보슈는 시간별 가변 생산, 60~100% 전력부하, 시간당 증산 2%·감산 20%, 암모니아 저장·출하를 적용한다.

먼저 하버보슈 정효율과 전해조 교체 MILP를 적용한 0차 해를 구한다. 이어 Fig. 5 기반 운전영역별 할선을 식 (15) 형태로 적용해 1차와 2차를 순서대로 푼다. 이전 단계의 운전영역은 다음 단계의 할선만 선택한다. 운전영역별 생산량 상·하한은 두지 않아 해가 다른 영역으로 이동할 수 있다. 정확한 영역 경계에서는 이전 영역을 유지한다. 이 영역 이동 방식은 원 논문의 구간 내 선형화와 다른 실험 설정이며, 모든 단계에서 전체 60~100% 전력부하 제약은 유지한다.

## 실행

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)를 설치하고 저장소 최상위 폴더에서 실행한다.

```powershell
uv sync
uv run python run_hb_region_milp.py
uv run python -m tests.test_modular_model
uv run python -m tests.test_region_migration
```

최적화는 Pyomo와 HiGHS를 사용한다. 8,760시간 계산은 오래 걸릴 수 있다. 0차 또는 1차가 저장된 상태에서 실행이 중단되었다면 `uv run python run_hb_region_milp.py --resume`으로 남은 단계를 이어서 푼다. `results/cambridge_2013_hb_region_milp_0_to_2/summary.json`은 세 단계의 지표를 담고 있다.

## 모듈

| 경로 | 역할 |
| --- | --- |
| `run_hb_region_milp.py` | 입력·설정, 0~2차 실행, 결과 저장 |
| `green_ammonia/renewables.py` | PVGIS·NEWA 자료를 시간별 용량계수로 변환 |
| `green_ammonia/assumptions.py` | 설비비, 효율, 원단위, 할인율, 설정 |
| `green_ammonia/hydrogen.py` | 정효율 전해조, H₂ 저장·압축, RO |
| `green_ammonia/nitrogen.py` | 공기분리장치와 N₂ 저장·압축 |
| `green_ammonia/ammonia.py` | 하버보슈 운전영역별 전력식, 램프, NH₃ 저장·출하 |
| `green_ammonia/battery.py` | 배터리 충·방전과 재고 |
| `green_ammonia/electricity.py` | 시간별 전력수지와 계통 구매 |
| `green_ammonia/replacement.py` | 식 (22)의 MILP 전해조 교체 시점·비용 |
| `green_ammonia/economics.py` | 설비비, 운영비, 교체비, 목적함수 |
| `green_ammonia/region_migration.py` | 예비 LP, 0차 MILP, HB 운전영역 재배정 및 1·2차 MILP |
| `green_ammonia/design.py` | 공정 모듈을 하나의 Pyomo 모델로 조립 |

## 저장된 결과와 해석 범위

포함된 입력에서 2차 LCOA는 **986.511 USD/t NH₃**다. 2차에서 전해조 345.708 MW, 하버보슈 11.671 t/h, 태양광 562.907 MW, 풍력 10.394 MW, 계통 구매 용량 3.689 MW가 선택되었다. 전해조 교체는 선택되지 않았다. 2차 뒤에도 198시간의 운전영역이 바뀌었으므로 수렴한 부분부하 최적해로 해석하지 않는다. 용량, 비용과 단계별 영역 변화는 [결과 요약](results/cambridge_2013_hb_region_milp_0_to_2/summary.json)을 참조한다.

원 논문과 입력 발전 자료, 출하 방식, 배터리 효율 및 운전영역 이동 규칙이 다르다. 따라서 저장된 값은 원 논문의 발표 수치와 직접 비교하는 재현 결과가 아니다. 이전 정효율·고정운전 구현은 Git 기록에서 확인할 수 있다.
