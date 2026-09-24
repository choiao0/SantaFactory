# -*- coding: utf-8 -*-
"""물리 검증 결과를 **숫자 한 벌**로 — `sim.verify.result.physics` 의 원천 (S15P21A106-275).

무엇을 재나
-----------
DES 피크 10분 구간을 Isaac 이 실제 시간으로 돌렸을 때(시뮬 1초 = 현실 1초):

    지연      동작마다 (실제 시작 − DES 계획 시작). 일찍은 못 가므로 늘 0 이상
    수행      창에 계획된 동작 중 창 끝까지 **시작한** 비율, 가장 오래 밀린 동작의 나이
    안전      로봇 접촉·최소 간격·랙 접촉·피커 구역 침범·정지·회전 포기
    대기      막힌 로봇-프레임을 원인별로 — 계획 시각 기다림(릴리스)·다른 로봇(ADG-남)

☹ 워밍업은 뺀다. 카운터는 워밍업이 끝나는 순간 `snapshot()` 을 떠 두고 그 뒤 차이만
  센다. 최솟값·최댓값(최소 간격·최대 침투)은 차이를 못 내므로 **런 전체** 값이다.

Isaac 에 기대지 않는 순수 함수라 여기만 따로 시험한다 (`path/test_physics_report.py`).
"""
import json
import math
import os

#: 카운터 — 워밍업 뒤 증분으로 센다. 없는 이름은 0 으로 읽는다(판마다 필드가 다를 수 있다).
COUNTERS = ("contact_events", "static_contact_events", "zone_intrusion_events",
            "stall_steps", "recover_events", "overlap_events", "started", "completed",
            "turn_gaveup_body", "turn_gaveup_park", "turn_gaveup_other")
WHY_NAMES = ("obstacle", "release", "adg_self", "adg_other")
LATE_S = 1.0                          # 「늦었다」로 세는 문턱 [s]


def _why_totals(rt):
    tot = [0, 0, 0, 0]
    for v in (getattr(rt, "_why", None) or {}).values():
        for i in range(4):
            tot[i] += int(v[i])
    return tot


def snapshot(stats, rt=None):
    """워밍업 끝 기준선 — 카운터와 막힘 프레임 합."""
    base = {k: int(getattr(stats, k, 0) or 0) for k in COUNTERS}
    base["why"] = _why_totals(rt)
    base["why_steps"] = int(getattr(rt, "_why_steps", 0) or 0) if rt is not None else 0
    return base


def _zero_base():
    base = {k: 0 for k in COUNTERS}
    base["why"] = [0, 0, 0, 0]
    base["why_steps"] = 0
    return base


def _pct(sorted_vals, q):
    """정렬된 값의 q 분위 (0..1), 최근접 순위. 비었으면 None."""
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, math.ceil(q * len(sorted_vals)) - 1))
    return sorted_vals[i]


def lag_summary(start_lag, lo_s, hi_s):
    """계획 시각이 [lo, hi) 인 동작의 시작 지연 분포."""
    lags = sorted(max(0.0, act - plan) for plan, act in start_lag if lo_s <= plan < hi_s)
    if not lags:
        return {"n": 0, "p50_s": None, "p90_s": None, "max_s": None, "mean_s": None,
                "late_ratio": None}
    return {"n": len(lags),
            "p50_s": round(_pct(lags, 0.5), 3),
            "p90_s": round(_pct(lags, 0.9), 3),
            "max_s": round(lags[-1], 3),
            "mean_s": round(sum(lags) / len(lags), 3),
            "late_ratio": round(sum(1 for x in lags if x > LATE_S) / len(lags), 4)}


def progress(planned_s, started_plans, lo_s, hi_s, now_s):
    """창 [lo, hi) 에 계획된 동작 중 `now` 까지 시작한 비율과 가장 오래 밀린 것의 나이.

    `planned_s`     모든 동작의 계획 시작 시각
    `started_plans` 시작한 동작의 계획 시각(같은 시각 동작이 여럿일 수 있다 — 다중집합)
    나이 = now − (아직 안 시작한 동작 중 가장 이른 계획 시각). 없으면 0.
    """
    end = min(hi_s, now_s)
    due = sorted(p for p in planned_s if lo_s <= p < end)
    started = sorted(p for p in started_plans if lo_s <= p < end)
    i = j = 0
    oldest = None
    while i < len(due):                       # 다중집합 차에서 가장 이른 것
        if j < len(started) and abs(started[j] - due[i]) < 1e-9:
            i += 1
            j += 1
        elif j < len(started) and started[j] < due[i]:
            j += 1
        else:
            oldest = due[i]
            break
    return {"planned": len(due), "started": len(started),
            "ratio": round(len(started) / len(due), 4) if due else None,
            "overdue_s": round(max(0.0, now_s - oldest), 3) if oldest is not None else 0.0}


def summarize(stats, base, *, sim_s, wall_s, warmup_s, window_s, n_robots,
              planned_s=(), rt=None, des_window=None, engine="isaac-headless"):
    """물리 블록 dict. `base` 가 None 이면(워밍업 전) 런 전체를 센다."""
    base = base or _zero_base()
    d = {k: int(getattr(stats, k, 0) or 0) - int(base.get(k, 0)) for k in COUNTERS}
    why_now = _why_totals(rt)
    why = [why_now[i] - base["why"][i] for i in range(4)]
    steps = (int(getattr(rt, "_why_steps", 0) or 0) - base["why_steps"]) if rt is not None else 0
    denom = steps * max(1, n_robots)
    gap = getattr(stats, "worst_gap", float("inf"))
    lo, hi = float(warmup_s), float(warmup_s) + float(window_s)
    started_plans = [plan for plan, _ in getattr(stats, "start_lag", ())]
    return {
        "engine": engine,
        "n_robots": n_robots,
        "sim_s": round(float(sim_s), 3),
        "window_sim_s": round(max(0.0, float(sim_s) - float(warmup_s)), 3),
        "warmup_s": float(warmup_s),
        "window_s": float(window_s),
        "wall_s": round(float(wall_s), 3),
        "rtf": round(float(sim_s) / float(wall_s), 3) if wall_s else None,
        "robot_contacts": d["contact_events"],
        "robot_min_gap_m": None if gap is None or math.isinf(gap) else round(float(gap), 4),
        "rack_contacts": d["static_contact_events"],
        "rack_worst_pen_mm": round(float(getattr(stats, "static_worst_pen", 0.0) or 0.0) * 1000, 1),
        "zone_intrusions": d["zone_intrusion_events"],
        "zone_worst_pen_mm": round(float(getattr(stats, "zone_worst_pen", 0.0) or 0.0) * 1000, 1),
        "stall_steps": d["stall_steps"],
        "turn_gaveup": d["turn_gaveup_body"] + d["turn_gaveup_park"] + d["turn_gaveup_other"],
        "recover_events": d["recover_events"],
        "cell_overlaps": d["overlap_events"],
        "actions_started": d["started"],
        "actions_completed": d["completed"],
        "lag": lag_summary(getattr(stats, "start_lag", ()), lo, hi),
        "window_actions": progress(planned_s, started_plans, lo, hi, float(sim_s)),
        "blocked": {"robot_frames": denom,
                    **{n: why[i] for i, n in enumerate(WHY_NAMES)},
                    "ratio": round(sum(why) / denom, 4) if denom else None},
        "des_window": des_window,
    }


def write_atomic(path, doc):
    """반쪽 파일이 안 남게 `.part` 로 쓰고 옮긴다 — 엣지가 아무 때나 읽는다."""
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
