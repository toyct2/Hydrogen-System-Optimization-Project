from __future__ import annotations

import pyomo.environ as pyo

from .assumptions import N2_COMP_MWH_PER_T_N2, N2_T_PER_NH3_T


def add_nitrogen_system(model: pyo.ConcreteModel, storage_enabled: bool) -> None:
    """논문 Eq. (12), (17)의 N2 버퍼를 구현한다.

    ASU 생산량은 HB가 그 시간에 소비하는 질소량과 다를 수 있다.
    차이는 질소 탱크 재고에 들어가며 연말 재고는 연초와 같다.
    storage_enabled=False이면 질소 탱크용량을 0으로 고정한다.
    """
    model.asu_tph = pyo.Var(domain=pyo.NonNegativeReals)
    model.n2_production = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.n2_compressor_mw = pyo.Var(domain=pyo.NonNegativeReals)
    model.n2_inventory = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.n2_tank_t = pyo.Var(domain=pyo.NonNegativeReals)

    # 논문 Eq. (12): ASU 전력 = sec_ASU × 시간별 N2 생산량.
    # 전력수지는 electricity.py에서 계산하고, 여기서는 생산 t/h의 상한을 둔다.
    model.asu_limit = pyo.Constraint(
        model.T, rule=lambda m, t: m.n2_production[t] <= m.asu_tph
    )
    # N2 압축은 논문 Sec. 3.4의 단위 전력소비량 × 생산량을 사용한다.
    # 별도 번호식은 없으며 그 소비전력은 논문 Eq. (1)의 우변에 합산된다.
    model.n2_compressor_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: N2_COMP_MWH_PER_T_N2 * m.n2_production[t]
        <= m.n2_compressor_mw,
    )
    # 논문 Eq. (17): 이전 N2 재고 + ASU 생산 = 현재 재고 + HB 투입.
    # (t - 1) % len(T)는 연말 재고를 첫 시간 직전 재고로 쓰는 순환 경계다.
    # HB 투입량 = 28/34 × NH3 생산량은 Sec. 3.4의 화학양론이다.
    model.n2_balance = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.n2_inventory[t]
        == m.n2_inventory[(t - 1) % len(m.T)]
        + m.n2_production[t]
        - N2_T_PER_NH3_T * m.nh3[t],
    )
    # 논문 Sec. 3.4의 저장용량 정의를 시간별 선형 부등식으로 쓴다.
    # H2 용량에 대한 논문 Eq. (20)과 같은 구조를 N2 탱크에도 적용한다.
    model.n2_capacity = pyo.Constraint(
        model.T, rule=lambda m, t: m.n2_inventory[t] <= m.n2_tank_t
    )
    # False는 Cambridge 단순화 모델처럼 같은 시간에 생산한 N2를 모두 쓰게 한다.
    # 현재 Argentina 실행에서는 True이므로 N2 저장량도 최적화 변수다.
    if not storage_enabled:
        model.n2_tank_t.fix(0)
