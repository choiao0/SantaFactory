# -*- coding: utf-8 -*-
"""처리량을 FMS `tasks_per_h` 와 같은 단위로 환산한다.

★ 왜 함수가 하나가 아니라 둘인가
--------------------------------
우리 계획기는 **틱**으로 돈다. ADG 실행기는 **사건**으로 돈다. 틱은 고정
시간이 아니다 — 전진 1칸, 제자리 회전, 후진이 서로 다른 시간을 쓰고, Isaac
안에서는 가감속·안전정지까지 붙는다. 그래서 "틱을 초로 바꾸는 상수" 하나로
환산하면 반드시 틀린다.

두 값을 따로 낸다.

    tasks_per_h_nominal    계획 격자 틱 x TICK_S. **FMS 와 비교할 값**이다.
                           FMS 도 틱 기반이므로 단위가 같다.
    tasks_per_h_realized   ADG 를 실제로 돌린 makespan 으로 나눈 값.
                           Isaac 이든 verify.Executor 든, 실측이 있을 때만.

makespan 이 없으면 `stretch`(실행/계획 비율)로 추정치를 낸다. 이 비율은
추측이 아니라 실측값이다 — 2026-09-06 Isaac 12대 주행에서

    액션 1037개 · 3.17 액션/s -> 325 s
    같은 계획의 명목 시간              189 s
    stretch = 325 / 189 = 1.72

이다. `--stretch` 로 갱신하라. 계획 격자·대수·맵이 바뀌면 다시 재야 한다.
"""

# 틱 모델 상수(MOVE_TICKS)는 FMS 원본에서 온다 — lifelong 과 같은 로더를 쓴다.
# 사본을 두면 상류가 바뀔 때 조용히 갈린다 (S15P21A106-141).
import pibt_core_v2 as _pc

# ★ stretch 는 상수가 아니라 **조건에 딸린 실측값**이다. 격자·실행속도가
#   바뀌면 같이 바뀐다. 기본값은 셸 기본 설정(pitch 1.0 · v_exec 미지정=0.9)에
#   맞춘다 — `run_record.sh` 가 PIBT_PITCH 를 1.0 으로, PIBT_V_EXEC 를 빈 값
#   (= geom.v_max 0.9) 으로 두기 때문이다.
#
#     pitch  v_exec   계획 s   실측 s   stretch   측정일
#      1.2     0.9      189     325      1.72     2026-09-06  (옛 기본값)
#      1.0     0.9      350     461.1    1.32     2026-09-15  <- 지금 기본
#      1.0     2.2      350     362.8    1.04     2026-09-15  (채택 검토 중)
#
#   1.72 를 pitch 1.0 에 그대로 쓰면 `horizon_for(clock="wall")` 이 30% 틀린다.
#   v_exec 2.2 를 채택하면 이 값을 1.04 로 내려야 한다.
STRETCH_MEASURED = 1.32


def tick_seconds(geom):
    """**한 틱**이 몇 초인가. FMS 틱과 같은 정의.

    ★ 2026-09-15 (S15P21A106-211): 전진 1칸이 ``MOVE_TICKS`` 틱이 되면서
    **틱 ≠ 칸**이 됐다. 전에는 전진이 1틱이라 이 함수가 「한 칸에 드는 시간」
    이기도 했지만 이제는 아니다.

        한 칸  = pitch / v_max                 = 1.1111 s  (pitch 1.0)
        한 틱  = pitch / (v_max x MOVE_TICKS)  = 0.2778 s

    호출부가 ``horizon x tick_seconds`` 로 계획 초를 내므로 **틱** 쪽이 맞다.
    ``HORIZON`` 도 같이 4배가 되어야 곱이 보존된다 — 한쪽만 바꾸면 릴리스
    지평이 4배 틀어지고 **아무 에러도 안 난다**. 아래 :func:`plan_seconds`
    불변식으로 막는다.

    가감속을 무시한 명목값이다 (직선 구간에서는 칸마다 멈추지 않는다).
    """
    return float(geom.pitch) / (float(geom.v_max) * _pc.MOVE_TICKS)


def cell_seconds(geom):
    """전진 **한 칸**에 드는 시간. ``tick_seconds x MOVE_TICKS``."""
    return float(geom.pitch) / float(geom.v_max)


def plan_seconds(horizon, geom):
    """``horizon`` 틱이 몇 초인가 — `HORIZON` 과 `tick_s` 의 **짝 불변식**.

    이 값은 틱 모델을 바꿔도 **변하지 않아야 한다.** pitch 1.0 · 12대 기준
    315틱 x 1.1111 = 1260틱 x 0.2778 = 350.0 s 다. 달라졌으면 둘 중 하나만
    고친 것이다.
    """
    return horizon * tick_seconds(geom)


def throughput(tasks_done, horizon, geom, makespan=None,
               stretch=STRETCH_MEASURED, kind="critical_path"):
    """FMS 와 같은 단위(`tasks_per_h`)로 환산한 처리량 딕셔너리.

    ``makespan`` 이 어디서 온 값인지 ``kind`` 로 반드시 표시한다.
        "critical_path"  ADG 최장경로 — 지연 0 인 이상적 실행. 계획 쪽 값이다.
        "measured"       Isaac / 실행기에서 실제로 잰 값.
    둘을 섞으면 "stretch" 의 의미가 달라져 조용히 잘못 읽힌다.
    """
    ts = tick_seconds(geom)
    plan_s = horizon * ts
    out = {
        "tick_s": round(ts, 4),
        "plan_s": round(plan_s, 1),
        "tasks_done": int(tasks_done),
        "tasks_per_h_nominal": round(3600.0 * tasks_done / plan_s, 1),
    }
    if makespan:
        out["makespan_s"] = round(float(makespan), 1)
        out["makespan_kind"] = kind
        out["ratio_to_plan"] = round(float(makespan) / plan_s, 2)
        out["tasks_per_h_realized"] = round(3600.0 * tasks_done / float(makespan), 1)
    else:
        out["stretch_assumed"] = stretch
        out["tasks_per_h_expected"] = round(
            3600.0 * tasks_done / (plan_s * stretch), 1)
    return out


def horizon_for(seconds, geom, clock="plan", stretch=STRETCH_MEASURED):
    """"N초 돌린다" -> 틱 수. **어느 N초인지**를 반드시 정해야 한다.

        clock="plan"  계획 시간. Isaac 에서는 stretch 배 더 걸린다.
        clock="wall"  Isaac 벽시계. 틱당 시간에 stretch 를 곱해서 센다.

    pitch 1.0 · stretch 1.32 기준 예시:

        horizon_for(350, geom, "plan")  -> 315틱  (계획 350 s = 실측 461 s)
        horizon_for(350, geom, "wall")  -> 239틱  (실측 350 s = 계획 266 s)

    FMS 와 숫자를 맞출 때는 plan, 심사 영상 길이를 맞출 때는 wall 이다.
    ``stretch`` 기본값의 조건은 STRETCH_MEASURED 옆 표를 볼 것 — 격자나
    실행 속도를 바꿨으면 그 값도 같이 줘야 한다.
    """
    ts = tick_seconds(geom)
    if clock == "wall":
        ts *= stretch
    elif clock != "plan":
        raise ValueError("clock 은 'plan' 또는 'wall'")
    return max(1, int(round(float(seconds) / ts)))


def _ramp_seconds(dist, v_max, accel):
    """대칭 사다리꼴 속도 프로파일. 정지에서 정지까지."""
    if dist <= 0.0:
        return 0.0
    d_ramp = v_max * v_max / accel          # 가속 + 감속 거리
    if dist <= d_ramp:
        return 2.0 * (dist / accel) ** 0.5
    return 2.0 * (v_max / accel) + (dist - d_ramp) / v_max


def action_seconds(geom, action, blend=True):
    """액션 하나의 소요 시간.

    ``blend=True`` 는 직선 구간에서 칸마다 멈추지 않는다고 보고 전진을
    ``cell_seconds`` 로 센다. False 면 액션마다 정지-정지 사다리꼴을 쓴다 —
    ADG 가 매번 대기하는 최악의 경우.

    ★ 액션 하나 = **한 칸**이지 한 틱이 아니다 (전진은 MOVE_TICKS 틱).
    """
    if action.frm[:2] == action.to[:2]:                       # 제자리 회전
        import math
        return _ramp_seconds(math.pi / 2.0, geom.w_max, geom.a_ang)
    if blend:
        return cell_seconds(geom)
    return _ramp_seconds(geom.pitch, geom.v_max, geom.a_lin)


def critical_path(adg, geom, blend=True):
    """ADG 의 최장 경로 = 지연이 전혀 없을 때의 실행 시간 [s].

    ``horizon x tick_s`` 와 다르다. 저쪽은 "틱이 몇 개인가"이고, 이쪽은
    "선행 제약을 지키면서 얼마나 병렬로 갈 수 있는가"다. 둘의 비율이 계획의
    동시성이고, 실측 makespan 과의 비율이 물리·안전정지의 대가다.
    """
    order = adg.topological_order()
    if order is None:
        raise RuntimeError("ADG 에 순환이 있다")
    by_uid = {a.uid: a for a in adg.actions}
    end = {}
    for uid in order:
        a = by_uid[uid]
        pre = max((end[u] for u in adg.preds[uid] if u in end), default=0.0)
        end[uid] = pre + action_seconds(geom, a, blend)
    return max(end.values(), default=0.0)


def fmt(th):
    """한 줄 출력."""
    head = (f"[처리량] 태스크 {th['tasks_done']}개 / 계획 {th['plan_s']}s "
            f"(틱 {th['tick_s']}s) = {th['tasks_per_h_nominal']} tasks/h (명목)")
    if "tasks_per_h_realized" in th:
        lbl = ("ADG 최장경로" if th["makespan_kind"] == "critical_path"
               else "실측")
        return head + (f"\n[처리량] {lbl} {th['makespan_s']}s "
                       f"(계획 대비 {th['ratio_to_plan']}배) = "
                       f"{th['tasks_per_h_realized']} tasks/h")
    return head + (f"\n[처리량] stretch {th['stretch_assumed']} 가정 = "
                   f"{th['tasks_per_h_expected']} tasks/h (추정)")
