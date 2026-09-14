# -*- coding: utf-8 -*-
"""ADG 비순환 검사 — 앞 칸 규칙을 켜고 여러 시드로 (설계서 §9 항목 2).

무엇을 묻나
-----------
pitch 1.0 에서 4칸 규칙을 켜면 ADG 에 순환이 생기는가.

단조 증명(`E_새 ⊆ TC(E_옛)`)은 **1.0 에서 쓸 수 없다.** 전제가 둘인데

    전제 1   guard ⊆ 실제스윕
    전제 2   axle ∩ guard = ∅

4칸의 섞임 대각 mA·mB 가 pitch 1.0 에서 **실제 스윕 밖**(0/8)이라 전제 1 이
깨진다. 유일하게 만족하는 앞2 조차, 1.0 의 옛 규칙(전부 hard)이 이미 순환이라
함의가 공허하다. **그래서 측정으로만 안다.**

무엇을 켜나
-----------
계획기와 ADG 가 **같은 함수**를 보게 한다.

    geo.configure(front_swing=True, front_diag=True,
                  robot_dims=(front_len, rear_len, width), pitch=pitch)
    RobotGeom(front_swing=geo.front_swing_on(), front_diag=geo.front_diag_on())

`robot_dims` 를 빼면 계획기가 pitch 게이팅을 통째로 건너뛴다. 반드시 넣는다
(우리 `_check_front_swing` (2) 가 그 경우를 잡는다).

FIXLIVE — 목표 앞 왕복 정체 회피
--------------------------------
2026-09-14 현재 계획기에 라이브락이 있어 12시드 중 3분의 2가 계획을 못
끝낸다 (`tools/goal_oscillation.py`). 원인은 대기 벌점이 목표 상태에도
붙는 것이고, 한 줄 수정을 우리가 검증했다.

    FIXLIVE=1  그 수정을 몽키패치로 얹고 잰다

    ★ 이 모드로 낸 결과는 **"FMS 수정안 적용 기준"** 이라고 반드시 명시할 것.
      계획기 실제 코드가 고쳐지면 FIXLIVE 없이 다시 돌려 확인한다.

쓰는 법
-------
    source paths.sh
    PITCH=1.0 SEEDS=1-20 FIXLIVE=1 python tools/adg_cycles.py
    PITCH=1.2 SEEDS=1-20 python tools/adg_cycles.py        규칙 게이팅으로 꺼짐
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                      # noqa: F401
import pibt.geometry as geo              # noqa: E402
import pibt.heading as HD                # noqa: E402
import isaac_drive as D                  # noqa: E402
import pibt_scene                        # noqa: E402

MAP = os.environ["MAP"]
PITCH = float(os.environ.get("PITCH", "1.0"))
N = int(os.environ.get("N", "12"))
STEPS = int(os.environ.get("STEPS", "2000"))
FIXLIVE = os.environ.get("FIXLIVE", "") not in ("", "0")
DIAG = os.environ.get("DIAG", "1") not in ("", "0")     # 4칸(=1) / 2칸(=0)

_spec = os.environ.get("SEEDS", "1-20")
if "-" in _spec and "," not in _spec:
    _a, _b = _spec.split("-")
    SEEDS = list(range(int(_a), int(_b) + 1))
else:
    SEEDS = [int(x) for x in _spec.split(",")]

_ORIG = HD.candidates_h


def _goal_exempt(s, dist, edge_cost, wait_cost, free, turn_cost, bias=0.0):
    """FMS 수정안 — 목표 상태(dist == 0)면 대기 벌점을 뺀다."""
    r, c, h = s
    if dist[r, c, h] == 0:
        bias = 0.0
    return _ORIG(s, dist, edge_cost, wait_cost, free, turn_cost, bias)


# 계획기(FMS)는 **풀 수 없는 시나리오를 SystemExit 로 알린다.**
#   `run_h` 독스트링: "전원 도달 못 하면 SystemExit"
#   `pibt_scene.setup` 도 맵·인자 문제를 같은 방식으로 낸다.
#
# 이 도구는 시드 20개를 훑어 **어느 것이 막히는지 표로 내는 것**이 목적이라
# 그 신호를 잡아야 한다. 다만 아무 SystemExit 이나 삼키면 안 된다 —
# `SystemExit` 를 내는 곳이 성격이 둘로 갈리기 때문이다.
#
#   [잡는다] 계획기 신호 — 이 시드만 못 푼다. 다음 시드는 의미가 있다
#     heading.py:350   "PIBT(헤딩) 정체: N스텝 내 미도달 {...}"     <- 이것 하나뿐
#
#   [안 잡는다] 설정 오류 — 전 시드가 똑같이 죽는다. 한 번 죽고 끝내야 한다
#     pibt_scene   맵 파일을 찾을 수 없습니다
#                  pitch 는 0.1 m 의 배수여야 합니다
#                  어느 성분에도 스테이션이 없습니다
#                  충전존에 N대를 놓을 자리가 없습니다
#                  CHARGE_STEP_X 가 pitch 의 2배 미만
#
# 설정 오류를 잡으면 "시나리오 실패: 맵 파일을 찾을 수..." 가 20번 찍힌다.
# 한 번 죽고 이유를 명확히 알려 주는 것보다 훨씬 나쁘다.
#
#   ★ `run_h` 의 "시작 상태 invalid" · "목표 도달 불가" 는 `assert` 라
#     **AssertionError** 다. SystemExit 로는 안 온다 — 여기 넣으면 죽은 항목이 된다.
_PLANNER_STALL = ("정체", "미도달")


def _planner_stalled(e: SystemExit) -> bool:
    """계획기가 낸 '이 시드는 못 푼다' 신호인가. 아니면 설정 오류다."""
    return any(k in str(e) for k in _PLANNER_STALL)


def _quiet(fn, *a, **kw):
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        return fn(*a, **kw)
    finally:
        sys.stdout = old


def _rule_on(pitch):
    """계획기에 규칙을 켜고 (켜짐, 대각, 이름) 을 돌려준다.

    `RULE=off` 면 대조군. `robot_dims` 를 반드시 넘긴다 — 빼면 계획기가 pitch
    게이팅을 통째로 건너뛴다 (우리 `_check_front_swing` (2) 가 그걸 잡는다).
    """
    dims = (pibt_scene.GEOM_KW["front_len"], pibt_scene.GEOM_KW["rear_len"],
            pibt_scene.GEOM_KW["width"])
    want = os.environ.get("RULE", "4").lower()
    geo.configure(front_swing=(want != "off"), front_diag=(want == "4"),
                  robot_dims=dims, pitch=pitch)
    on, diag = geo.front_swing_on(), geo.front_diag_on()
    name = "4칸" if diag else ("앞2" if on else "규칙 꺼짐 (대조군)")
    return on, diag, name, dims


def _one_seed(seed, on, diag):
    """시드 하나 — (비순환 여부, 출력줄) 을 돌려준다. 비순환이 None 이면 실패."""
    import dataclasses

    # ★ `setup` 은 **안 잡는다.** 거기서 나오는 SystemExit 은 전부 설정 오류
    #   (맵 없음·pitch 배수·스테이션 없음·충전존 부족)라 시드별로 다를 수가
    #   없다. 잡으면 같은 메시지가 20번 찍힐 뿐이고, 한 번 죽는 편이 낫다.
    geom, free, starts, goals = _quiet(
        pibt_scene.setup, MAP, N, PITCH, seed, "cross")

    geom = dataclasses.replace(geom, front_swing=on, front_diag=diag)
    try:
        hist, _ = _quiet(HD.run_h, free, starts, goals, max_steps=STEPS)
    except SystemExit as e:
        if not _planner_stalled(e):
            raise           # 계획기 정체가 아니면 설정 오류다 — 삼키지 않는다
        m = str(e)
        who = m.split("미도달")[-1].strip() if "미도달" in m else m[:24]
        return None, f"계획 정체 {who}"

    try:
        chains, _order, _ = D.extract_actions(hist, geom)
        adg = D.build_adg(chains, geom)
    except RuntimeError as e:
        return None, f"★ {str(e).splitlines()[0][:46]}"

    acyc = adg.topological_order() is not None
    # 규칙 ② 가 실제로 간선을 만들었나 — guard 를 가진 액션 수로 가늠
    nsoft = sum(1 for a in adg.actions if a.guard)
    row = (f"{len(adg.actions):>8}{adg.type1:>8}{adg.type2:>8}"
           f"{nsoft:>9}{str(acyc):>8}")
    return acyc, row


def _verdict(ok, cyc, fail, total):
    """★ 두 질문을 섞지 않는다.

    순환 여부는 **계획이 나온 시드**로 답한다. 계획 실패는 계획기 쪽 별개
    항목이고, 그것 때문에 순환 결론을 못 낸다고 하면 과하다.
    """
    print()
    print(f"  비순환 {ok} · 순환 {cyc} · 계획 실패 {fail}   (시드 {total}개)")
    if cyc:
        print("  ★ 순환이 있다. 1.0 에서는 단조 증명이 안 쓰이므로 이 결과가")
        print("    유일한 근거다 — 규칙을 줄이거나 다른 대책이 필요하다.")
    elif ok:
        print(f"  순환 0 / {ok}시드 — 이 규칙은 ADG 순환을 만들지 않는다")
        print("  (설계서 §9 항목 2). 1.0 에서는 증명이 안 쓰이므로 이것이 근거다.")
    else:
        print("  계획이 하나도 안 나와 순환을 묻지 못했다.")
    if fail:
        print(f"  계획 실패 {fail}건은 **별개**다 — 계획기 쪽 항목이고, 위")
        print("  순환 결론에는 영향이 없다. 다만 그 시드는 안 세었다.")


def _header(rule, on, diag, dims):
    print(f"ADG 비순환 검사 — pitch {PITCH} · {N}대 · cross · 시드 {len(SEEDS)}개")
    print(f"  규칙 {rule}   (front_swing={on}, front_diag={diag}, "
          f"robot_dims={dims})")
    print(f"  라이브락 수정안 {'적용' if FIXLIVE else '없음'}"
          f"{'   <- 결과에 명시할 것' if FIXLIVE else ''}")
    print(f"  front_cells((5,5,1)->(5,5,0)) = {sorted(geo.front_cells(5, 5, 1, 0))}")
    print()
    print(f"  {'시드':>5}{'액션':>8}{'type1':>8}{'type2':>8}{'soft간선':>9}"
          f"{'비순환':>8}   비고")


# 종료 코드 — CI 가 이걸로 판단한다.
#   0  순환 없음
#   1  **순환 있음** — 그 규칙은 그 pitch 에서 못 쓴다
EXIT_OK, EXIT_CYCLE = 0, 1


def main():
    on, diag, rule, dims = _rule_on(PITCH)
    if FIXLIVE:
        HD.candidates_h = _goal_exempt
    _header(rule, on, diag, dims)

    ok = cyc = fail = 0
    for seed in SEEDS:
        acyc, row = _one_seed(seed, on, diag)
        if acyc is None:
            print(f"  {seed:>5}{'':>33}   {row}")
            fail += 1
        else:
            print(f"  {seed:>5}{row}")
            ok += acyc
            cyc += (not acyc)

    HD.candidates_h = _ORIG
    _verdict(ok, cyc, fail, len(SEEDS))
    return EXIT_CYCLE if cyc else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
