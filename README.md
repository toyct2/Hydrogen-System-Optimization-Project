# 재생에너지 기반 그린 암모니아 설비용량 최적화

2013년 PVGIS 태양광·NEWA 풍력 자료를 입력으로 받아, 암모니아를 연간 83,950 t 생산하는 설비의 용량과 시간별 운전을 최적화한다. 수소·질소·암모니아 공정과 비용식은 [Schmidhalter et al. (2025)](https://doi.org/10.1016/j.ijhydene.2025.03.317)의 정효율 선형모델을 바탕으로 구현했다. 발전 입력은 [Smith and Torrente-Murciano (2025)](https://doi.org/10.1038/s44286-025-00207-9)의 위치·연도에 맞춰 공개 자료에서 준비했다.

## 모델 구성

```text
태양광·풍력 ──→ 전력망 ──↔ 배터리(BESS)
                    ├──→ RO 정수 ──→ 알칼라인 전해조 ──→ H₂ 압축·저장 ──┐
                    ├──→ 공기분리장치(ASU) ──→ N₂ 압축·저장 ────────────┤
                    └──→ 하버보슈 공정 ←───────────────────────────────┘
                              ↓
                         NH₃ 생산·출하
```

태양광·풍력·전해조·배터리·물질 탱크·ASU·압축기·RO·하버보슈 설비의 용량과 8,760시간의 운전을 함께 결정한다. 입력 자료와 변환 과정은 [발전 데이터 설명](data/benchmark_cambridge/README.md), 변수와 수식은 [코드 사용 가이드](docs/MODULAR_MODEL_GUIDE_KO.md)에 정리했다.

## 실행 방법

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)를 설치한 뒤 이 저장소의 최상위 폴더에서 실행한다.

```powershell
uv sync
uv run python run_cambridge_argentina_modular.py
uv run python -m tests.test_modular_model
```

`uv sync`는 `uv.lock`에 고정된 패키지 버전으로 실행환경을 준비한다. 최적화에는 Pyomo와 HiGHS를 사용한다. 필요한 PVGIS·NEWA 입력 파일은 `data/benchmark_cambridge/`에 포함되어 있다. 두 번째 명령은 최적화 결과를 `results/cambridge_2013_argentina_modular/`에 저장하고, 세 번째 명령은 모델의 기본 검사를 실행한다.

## 코드와 결과 파일

| 경로 | 역할 |
| --- | --- |
| `run_cambridge_argentina_modular.py` | 입력·설정 로드, 최적화 실행, 결과 저장 |
| `green_ammonia/renewables.py` | PVGIS·NEWA 원자료를 시간별 용량계수로 변환 |
| `green_ammonia/assumptions.py` | 설비비, 효율, 에너지 원단위, 할인율, 실행 설정 |
| `green_ammonia/hydrogen.py` | 전해조, H₂ 저장·압축, RO 용량 제약 |
| `green_ammonia/nitrogen.py` | 공기분리장치, N₂ 저장·압축 |
| `green_ammonia/ammonia.py` | 하버보슈 운전, NH₃ 저장·출하 |
| `green_ammonia/battery.py` | 배터리 충·방전과 에너지 재고 |
| `green_ammonia/electricity.py` | 시간별 전체 전력수지 |
| `green_ammonia/economics.py` | 설비비, 운영비, 교체비, 목적함수 |
| `green_ammonia/design.py` | 각 모듈을 하나의 Pyomo 모델로 조립 |
| `results/cambridge_2013_argentina_modular/summary.json` | 최적 설비용량, 연간 비용, LCOA, 수지 오차 |
| `results/cambridge_2013_argentina_modular/hourly.csv` | 시간별 발전·생산·저장·충방전량 |

## 저장된 실행 결과

포함된 2013년 입력과 고정 하버보슈 설정으로 구한 최적해의 LCOA는 **1,185.97 USD/t NH₃**다.

| 설비 | 최적 용량 |
| --- | ---: |
| 태양광 | 499.55 MW |
| 풍력 | 170.65 MW |
| 알칼라인 전해조 | 304.32 MW |
| 배터리 | 18.07 MW / 51.42 MWh |
| H₂ 탱크 | 213.68 t |
| N₂ 탱크 | 68.77 t |

전체 설비용량과 비용 항목은 `summary.json`에 있다. 저장된 결과의 풀이 상태는 `optimal`이며, 전력·H₂·N₂·NH₃·배터리 수지의 최대 절대오차는 각각 `2e-11` 이하이다.

## 결과를 읽을 때 적용되는 설정

- 하버보슈 생산량과 암모니아 출하량은 매시간 230/24 t으로 일정하며 계통전력은 사용하지 않는다. 이 설정에서 NH₃ 탱크용량은 0이다.
- 전해조 효율과 하버보슈 전력 원단위는 운전 부하에 관계없이 일정하다. 최적화는 8,760시간의 발전 자료를 모두 알고 설비와 운전을 동시에 결정한다.
- 배터리 왕복효율은 90%로 설정하고, 교체비는 사업기간 25년 중 8·16·24년을 반영한다. 전해조 교체비는 이 실행의 비용식에 포함되지 않으며, 풀이 뒤 25년 누적 등가 전부하시간이 80,000시간 미만인지 검사한다.
- `hourly.csv`의 배터리 충·방전량은 동시 충·방전이 있던 LP 해를 같은 SOC 변화의 단일 방향 운전으로 바꾼 값이다. LCOA와 설비용량은 후처리 전 최적해에서 계산한다.

자료의 위치·연도, 고정 생산·출하 설정, 정효율 가정이 다르므로 저장된 LCOA는 위 두 논문의 발표 수치와 직접 대응하지 않는다. 비용·설비용량의 해석에는 [코드 사용 가이드](docs/MODULAR_MODEL_GUIDE_KO.md)의 입력과 식을 함께 확인하면 된다.
