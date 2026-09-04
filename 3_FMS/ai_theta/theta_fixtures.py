# -*- coding: utf-8 -*-
# ============================================================
# 규칙별 θ 검증 세트 — from_theta 배관 확인용 (S15P21A106-126)
#
# 각 세트는 GuidanceTheta.neutral()에서 "규칙 하나"만 켠다. 나머지 배율이 전부
# 1.0이므로, 히트맵에 나타난 패턴은 그 규칙이 만든 것이라고 확신할 수 있다.
# 전 파라미터를 동시에 극단으로 놓으면(contracts/tests의 theta_at_upper_bounds)
# 범위 검증에는 쓸 수 있지만 어느 규칙이 어느 패턴을 만들었는지 구분할 수 없다.
#
# from_theta 자체의 성질 검산(중립 uniform / 포화 없음 / 배타 규칙 / station
# entry_dir / 교차로 경계)은 sim_engine/from_theta_demo.py 가 이미 [1]~[5]로
# 수행한다. 이 모듈은 그쪽이 다루지 않는 부분을 채운다:
#
#   - 범주형 3개(aisle_period, aisle_phase, loop_dir)를 기본값 이외의 값으로 검증
#     (demo는 전부 neutral 기본값 period=1 / phase=0 / loop_dir=0 만 사용)
#   - 하드코딩 dict 대신 이름 붙은 재사용 가능한 세트로 노출
#   - 기대 히트맵을 문자열로 함께 보관 — 히트맵을 보고 맞는지 틀린지 판정할 기준
#
# ⚠️ 격리에는 한계가 있다 (2026-09-03 실측으로 확인)
#   배타 순서는 θ 값이 아니라 **기하**로 판정된다. from_theta 는 간선이 상위 그룹
#   마스크에 걸리면 그 배율이 중립 1.0이어도 '적용됨'으로 표시하고, 뒤 그룹은
#   건너뛴다. 따라서 다른 파라미터를 1.0으로 두는 것만으로 규칙이 완전히 격리되지
#   않는다 — 상위 그룹이 선점한 간선에서는 격리한 규칙의 효과가 아예 보이지 않는다.
#
#     선점 순서: station_spur > loop > intersection_entry > aisle_interior
#
#   실측 wallA에서는 LOOP 세트가 셀 1개(43,93)에서 이 경우에 해당한다. 히트맵을
#   볼 때 "몇몇 간선만 1.0으로 남았다"면 버그가 아니라 이 선점일 수 있다.
#
# 사용:
#   from ai_theta.theta_fixtures import FIXTURES, by_name
#   g = from_theta(free, topo, by_name("AISLE_PERIOD_2").theta)
#
# 표로 보기: python ai_theta/theta_fixtures.py
# ============================================================
from dataclasses import dataclass, replace
import os
import sys
from typing import Optional, Tuple

_FMS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 3_FMS/
if _FMS_ROOT not in sys.path:
    sys.path.insert(0, _FMS_ROOT)
from contracts.guidance_types import GuidanceTheta  # noqa: E402

# 방향 — 명세 §3-2 (북0 동1 남2 서3)
N, E, S, W = 0, 1, 2, 3

# wallA 세로 통로 개수 (sim_engine/from_theta.py VA_XS_M). aisle_rank = 0..10
N_VERTICAL_AISLES = 11


@dataclass(frozen=True, eq=False)
class ThetaFixture:
    """θ 세트 하나 + 그 세트로 from_theta를 돌렸을 때의 기대 결과."""

    name: str
    rule: str                  # 격리한 규칙 (EDGE_RULE_PRECEDENCE 그룹 또는 main_aisle_gain)
    overrides: dict            # neutral()에서 바꾼 필드만
    expected: str              # 히트맵에 나와야 하는 것
    failure_hint: str          # 다르게 나오면 의심할 것
    # 통로 교번 세트에만 있음: 통로 rank 0..10 의 기대 선호 방향 (N 또는 S).
    # from_theta 의 group 공식을 쓰지 않고 손으로 계산한 값이라 공식 버그를 잡는다.
    aisle_pref: Optional[Tuple[int, ...]] = None

    @property
    def theta(self) -> GuidanceTheta:
        return replace(GuidanceTheta.neutral(), **self.overrides).validate()


def _f(name, rule, overrides, expected, failure_hint, aisle_pref=None):
    return ThetaFixture(name=name, rule=rule, overrides=overrides,
                        expected=expected, failure_hint=failure_hint,
                        aisle_pref=aisle_pref)


# ── 통로 교번 (aisle_interior) ────────────────────────────────────────────────
# group = (rank // period + phase) % 2,  group 0 → 북 선호, group 1 → 남 선호
# 아래 aisle_pref 는 그 공식을 손으로 전개한 결과다. 공식을 다시 쓰지 않는 게 요점.
_AISLE_ONEWAY = dict(aisle_alt_gain=3.5, aisle_alt_boost=0.5)

AISLE_ONEWAY_MAX = _f(
    "AISLE_ONEWAY_MAX", "aisle_interior", _AISLE_ONEWAY,
    "통로 내부 간선이 통로마다 방향 교번. 선호 방향 0.5 / 역방향 3.5. "
    "외곽 링(남·북·서·동 밴드)에는 줄무늬가 없어야 한다. 링은 loop 그룹이 선점한다.",
    "링에도 줄무늬가 보이면 EDGE_RULE_PRECEDENCE 배타 규칙이 적용되지 않은 것.",
    # period=1 phase=0 → rank 짝수 북 / 홀수 남
    aisle_pref=(N, S, N, S, N, S, N, S, N, S, N),
)

AISLE_PHASE_1 = _f(
    "AISLE_PHASE_1", "aisle_interior", dict(_AISLE_ONEWAY, aisle_phase=1),
    "AISLE_ONEWAY_MAX 와 통로별 방향이 정확히 반대.",
    "AISLE_ONEWAY_MAX 와 같게 나오면 aisle_phase 가 무시된 것.",
    # phase=1 → 짝수 남 / 홀수 북
    aisle_pref=(S, N, S, N, S, N, S, N, S, N, S),
)

AISLE_PERIOD_2 = _f(
    "AISLE_PERIOD_2", "aisle_interior", dict(_AISLE_ONEWAY, aisle_period=2),
    "두 통로마다 방향이 뒤집힘 (rank 0,1 북 / 2,3 남 / 4,5 북 …).",
    "매 통로 뒤집히면 aisle_period 가 무시된 것.",
    # rank//2 % 2
    aisle_pref=(N, N, S, S, N, N, S, S, N, N, S),
)

AISLE_PERIOD_3 = _f(
    "AISLE_PERIOD_3", "aisle_interior", dict(_AISLE_ONEWAY, aisle_period=3),
    "세 통로마다 방향이 뒤집힘 (rank 0~2 북 / 3~5 남 / 6~8 북 / 9,10 남).",
    "period=2 와 같게 나오면 나눗셈 몫이 아니라 나머지를 쓴 것.",
    # rank//3 % 2
    aisle_pref=(N, N, N, S, S, S, N, N, N, S, S),
)

# ── 순환로 (loop) ────────────────────────────────────────────────────────────
LOOP_ONEWAY_CW = _f(
    "LOOP_ONEWAY_CW", "loop", dict(loop_gain=3.0, loop_dir=0),
    "외곽 링에서 시계 방향의 역방향 간선만 3.0. 순방향과 링 수직·이탈 간선은 1.0. "
    "남 밴드 순방향 = 서, 북 밴드 순방향 = 동. "
    "예외 두 곳은 1.0으로 남는다: 링 경계(양 끝이 링이어야 적용), "
    "그리고 station 스퍼와 겹치는 간선(상위 그룹 선점, wallA 실측 1개 셀).",
    "양방향 다 비싸면 loop_pref 계산이 틀린 것. 순방향이 비싸면 부호가 반대.",
)

LOOP_ONEWAY_CCW = _f(
    "LOOP_ONEWAY_CCW", "loop", dict(loop_gain=3.0, loop_dir=1),
    "LOOP_ONEWAY_CW 와 비싼 방향이 정확히 반대. "
    "남 밴드에서 서행이 3.0, 북 밴드에서 동행이 3.0.",
    "CW 와 같게 나오면 loop_dir 이 무시된 것.",
)

# ── 큰 통로 (main_aisle_gain, 항상 곱) ───────────────────────────────────────
MAIN_AISLE_PREFER = _f(
    "MAIN_AISLE_PREFER", "main_aisle_gain", dict(main_aisle_gain=0.5),
    "양 끝이 모두 큰 통로(남·북 밴드)인 간선만 0.5. 나머지는 전부 1.0. "
    "밴드 경계를 넘는 간선(한쪽 끝만 밴드)은 1.0이다.",
    "경계 간선도 0.5면 '양 끝' 조건이 빠진 것. 이러면 큰 통로 진입에 할인이 걸려 "
    "'내부 주행 배율'이라는 의미가 깨진다.",
)

# ── 교차로 / station — demo [4]가 이미 검증. 재사용을 위해 이름만 붙여 둔다 ──
JUNCTION_AVOID_MAX = _f(
    "JUNCTION_AVOID_MAX", "intersection_entry", dict(junction_penalty=3.0),
    "비교차로 셀 → 교차로 셀 경계 간선만 3.0. 교차로 내부 이동과 이탈은 1.0.",
    "교차로 내부까지 3.0이면 '경계 1회' 규칙이 빠져 마스크 크기만큼 중복 과금된다.",
)

STATION_ONEWAY = _f(
    "STATION_ONEWAY", "station_spur", dict(station_in=0.5, station_out=3.0),
    "도킹 칸으로 들어가는 간선 0.5 / 진입로를 되돌아 나가는 간선 3.0. "
    "다른 출구 방향은 1.0.",
    "싼 쪽과 비싼 쪽이 뒤바뀌면 station_entry_dir 를 이동 방향으로 잘못 읽은 것 "
    "(명세 §6-3은 station→통로 방향이므로 진입 이동은 (entry_dir+2)%4).",
)

NEUTRAL = _f(
    "NEUTRAL", "-", {},
    "전 셀 전 방향 1.0 균일. wait_cost 도 1.0.",
    "균일하지 않으면 어딘가에서 의도치 않은 배율이 곱해진 것. "
    "이게 깨지면 다른 세트의 결과는 볼 필요가 없다.",
)

FIXTURES = (
    NEUTRAL,
    AISLE_ONEWAY_MAX,
    AISLE_PHASE_1,
    AISLE_PERIOD_2,
    AISLE_PERIOD_3,
    LOOP_ONEWAY_CW,
    LOOP_ONEWAY_CCW,
    MAIN_AISLE_PREFER,
    JUNCTION_AVOID_MAX,
    STATION_ONEWAY,
)

AISLE_FIXTURES = tuple(f for f in FIXTURES if f.aisle_pref is not None)


def by_name(name):
    for f in FIXTURES:
        if f.name == name:
            return f
    raise KeyError(f"그런 세트 없음: {name} (있는 것: {[f.name for f in FIXTURES]})")


def _main():
    print(f"규칙별 θ 검증 세트 {len(FIXTURES)}개\n")
    for f in FIXTURES:
        changed = ", ".join(f"{k}={v}" for k, v in f.overrides.items()) or "(없음: 전부 1.0)"
        print(f"── {f.name}  [규칙: {f.rule}]")
        print(f"   켠 값 : {changed}")
        print(f"   기대   : {f.expected}")
        print(f"   틀리면 : {f.failure_hint}")
        if f.aisle_pref:
            pref = " ".join("N" if d == N else "S" for d in f.aisle_pref)
            print(f"   통로별 : rank 0..{len(f.aisle_pref) - 1} → {pref}")
        print()


if __name__ == "__main__":
    _main()
