# -*- coding: utf-8 -*-
import json
import math
import os

import numpy as np

from pibt_core import TURN_TICKS

from map_loader import CELL_M

from .common import OUT, SPEED
from .export_isaac import export_isaac


def _mean(x):
    return float(x.mean()) if len(x) else 0.0


def _p90(x):
    return float(np.percentile(x, 90)) if len(x) else 0.0


def _header_line(a, kernel, stream, ctx, lifelong):
    """[1] 실행 조건 한 줄."""
    return (f"[1] 맵={a.variant}, {ctx.H}x{ctx.W}, 로봇 {a.n_robots}대, 주문 {a.n_orders}건"
            + (f" + 입고 {stream.n_inbound}건" if a.flow == "main" else "")
            + f", seed={a.seed}, flow={a.flow}, 통로차단={'ON' if a.aisle_block else 'OFF'}"
            + (f", 헤딩 모델(회전 {TURN_TICKS}틱)" if kernel.heading else "")
            + ("" if math.isclose(a.speed, SPEED) else f", 속도 {a.speed:g} m/s (틱 {a.dt:g} s)")
            + (f", 충전 존({len(kernel.zone_cells)}칸, 홈 간격≥2)" if kernel.zone else ", 고정 홈 12칸")
            + (f", 주문 간격 {a.order_gap:g}틱" if a.order_gap_arg is not None else "")
            + (f", 입고 간격 {a.inbound_gap_arg:g}틱" if a.inbound_gap_arg is not None else "")
            + (f", 고정 시간 {a.horizon}틱 = {a.horizon*a.dt/3600:.1f}h, 교대 {'/'.join(a.shifts)} "
               + " ".join(f"{k}[{s},{e})" for k, s, e in stream.windows) if lifelong else "")
            + (f", 배터리(도크 {len(kernel.docks)}, 가동 {a.runtime_h:g}h/충전 {a.charge_h:g}h, "
               f"SoC {a.soc[0]*100:.0f}/{a.soc[1]*100:.0f}/{a.soc[2]*100:.0f}%)" if a.battery else ""))


def _print_completion(a, kernel, tasks_done, orders_done, T_END, lifelong):
    """[2] 완료 수 (고정 시간 모드는 입고/출고·미완료·주문 완료 포함)."""
    n_tasks = len(tasks_done)
    if lifelong:
        n_in = sum(1 for tk in tasks_done if tk["kind"] == "in")
        print(f"[2] 완료: 태스크 {n_tasks}개 (입고 {n_in} / 출고 {n_tasks - n_in}), 미완료 {kernel.n_submitted - n_tasks}개, "
              f"주문 완료 {orders_done}/{a.n_orders}, 고정 시간 {T_END}틱 = {T_END*a.dt/3600:.2f}h")
    else:
        print(f"[2] 완료: 태스크 {n_tasks}개, makespan {T_END}틱 = {T_END*a.dt/60:.1f}분")


def _print_kpi(kernel, tot, n_tasks, sim_hours, orders_ph, lat, util, util_incl, conflict_wait):
    """[3] 처리량·리드타임·가동률 줄."""
    lat_total, lat_drive, lat_queue = lat
    print(f"[3] 처리량: {n_tasks/sim_hours:.0f} 태스크/시간 ({orders_ph:.0f} 주문/시간)")
    print(f"    대기(생성→배차): 평균 {_mean(lat_queue):6.1f}s / p90 {_p90(lat_queue):6.1f}s")
    print(f"    주행(배차→완료): 평균 {_mean(lat_drive):6.1f}s / p90 {_p90(lat_drive):6.1f}s")
    print(f"    총 리드타임    : 평균 {_mean(lat_total):6.1f}s / p90 {_p90(lat_total):6.1f}s")
    print(f"    가동률(v1호환) {util*100:.0f}% (서비스 포함 {util_incl*100:.0f}%) / "
          f"충돌대기 {conflict_wait*100:.1f}% / 밀림 {tot['pushed']}틱 / "
          f"태스크당 회전 {tot['turns']/max(n_tasks,1):.1f}회"
          + (f" / 회전 소모 {tot['rot']}틱 (비임무 회전 {tot['turns_idle']}회) / 후진 {tot['rev']}칸 / 재계획 {tot['replan']}틱"
             if kernel.heading else ""))


def _zone_section(a, kernel, tot):
    """충전 존 지표 출력 → SUMMARY 조각. 존 아니면 {}."""
    if not kernel.zone:
        return {}
    zs = kernel.zone_stats
    # 존 체류 분포: 틱별 존 안 로봇 수의 평균·p90 (시작·종료의 '전원 존 안'은 포함 — 실행이 길수록 희석).
    # 견적용 "존이 실제로 얼마나 차는가". 최대치는 항상 n 이라 의미 없어 제외 (B0″ §2).
    occ = np.array(zs["occ"] or [a.n_robots], dtype=float)
    zone_occ_mean, zone_occ_p90 = float(occ.mean()), float(np.percentile(occ, 90))
    print(f"    충전 존: 존 안 복귀 대기 {zs['wait']}틱 / 재선택 {zs['retargets']}회 / "
          f"예약 무시 {zs['degraded']}회 / 존 체류 평균 {zone_occ_mean:.1f}대 (p90 {zone_occ_p90:.0f}) / "
          f"비임무 밀림 이동 {tot['idle_moves']}칸")
    return dict(zone=1, zone_wait_steps=int(zs["wait"]), zone_retargets=int(zs["retargets"]),
                zone_degraded=int(zs["degraded"]), zone_occ_mean=round(zone_occ_mean, 2),
                zone_occ_p90=round(zone_occ_p90, 1), idle_moves=int(tot["idle_moves"]))


def _lifelong_section(a, kernel, tasks_done, orders_done):
    """고정 시간 모드 SUMMARY 조각 + 무진전 경고. 유한 모드면 {}."""
    if a.horizon is None:
        return {}
    n_tasks = len(tasks_done)
    n_in = sum(1 for tk in tasks_done if tk["kind"] == "in")
    extra = dict(horizon_steps=int(a.horizon), shifts=",".join(a.shifts), orders_done=int(orders_done),
                 open_tasks=int(kernel.n_submitted - n_tasks), tasks_in=int(n_in), tasks_out=int(n_tasks - n_in),
                 stall_warnings=len(kernel.stall_warning_ticks))
    if kernel.stall_warning_ticks:
        print(f"[WARN] 고정 시간 모드: {kernel.cfg.stall_ticks}틱 완료 무진전 {len(kernel.stall_warning_ticks)}회 "
              f"(계속 실행, 첫 시각 t={kernel.stall_warning_ticks[0]})")
    return extra


def _battery_section(a, kernel, T_END):
    """[5] 배터리 지표 출력 → SUMMARY 조각. 배터리 아니면 {}."""
    if not a.battery:
        return {}
    b = kernel.battery_summary()
    dock_util = b["charging_steps"] / (b["n_docks"] * T_END)
    print(f"[5] 배터리: 충전 진입 {b['charge_events']}회 (퇴거 {b['charge_evictions']}회) / 충전 {b['charging_steps']}틱 "
          f"(도크 가동률 {dock_util*100:.0f}%) / 도크 대기 {b['dock_wait_steps']}틱 / "
          f"SoC 최저 {b['soc_min']*100:.1f}% · 종료 평균 {b['soc_end_mean']*100:.1f}% / 0% 체류 {b['soc_empty_steps']}틱")
    return dict(battery=1, chargers=int(b["n_docks"]), charge_events=int(b["charge_events"]),
                charging_steps=int(b["charging_steps"]), dock_wait_steps=int(b["dock_wait_steps"]),
                charge_evictions=int(b["charge_evictions"]), soc_min=round(b["soc_min"] * 100, 1),
                soc_end_mean=round(b["soc_end_mean"] * 100, 1), soc_empty_steps=int(b["soc_empty_steps"]),
                dock_util=round(dock_util, 3))


def _tote_section(a, kernel, stream):
    """토트 적재 SUMMARY(v2.6). 명시 주문 전용 키만 조건부로 덧붙인다."""
    extra = dict(capacity=int(a.capacity), tote_units=a.tote_units,
                 totes=int(stream.totes_total), trips=int(kernel.trips),
                 orders_oversize=int(stream.orders_oversize))
    if stream.explicit_orders is not None:
        extra.update(orders_file=1, orders_skipped=int(stream.orders_skipped), max_order_totes=int(a.max_order_totes))
    return extra


def _make_tag(a, kernel, lifelong):
    """히트맵·DIRFLOW 파일 이름 태그."""
    return (f"sim_v2_{a.variant}_r{a.n_robots}{'_blk' if a.aisle_block else ''}_{a.flow}"
            f"{'_th' if a.theta_path else ''}{'_h' if kernel.heading else ''}"
            f"{'_ln' if a.lanes else ''}"
            f"{'_yr' if a.yield_rule else ''}"
            f"{'_fh' if (a.flow == 'main' and not kernel.zone) else ''}"
            f"{'_hz' if lifelong else ''}{'_bat' if a.battery else ''}")


def report(a, kernel, stream, ctx):
    lifelong = a.horizon is not None
    tasks_done = kernel.tasks_done
    # 고정 시간 모드의 분모는 T (Lifelong: T 안의 완료 수), 리드타임 표본은 T 안에 완료된 태스크만 (-145 §1-1)
    T_END = a.horizon if lifelong else max(tk["completed"] for tk in tasks_done)
    n_tasks = len(tasks_done)
    dt = a.dt                                            # 틱 길이[초] (-116: --speed)
    lat_total = np.array([tk["completed"] - tk["created"] for tk in tasks_done]) * dt
    lat_drive = np.array([tk["completed"] - tk["assigned"] for tk in tasks_done]) * dt
    lat_queue = np.array([tk["assigned"] - tk["created"] for tk in tasks_done]) * dt
    sim_hours = T_END * dt / 3600
    tot = kernel.totals()
    busy_v1 = tot["drive"] + 2 * tot["wait"]              # v1 호환 (대기 이중계산, 서비스 제외)
    util = busy_v1 / (a.n_robots * T_END)
    util_incl = (tot["drive"] + tot["wait"] + tot["svc"] + tot["rot"]) / (a.n_robots * T_END)
    conflict_wait = tot["wait"] / max(busy_v1, 1)
    orders_done = sum(1 for od in stream.orders.values() if od["completed"] is not None)
    order_lat = np.array([od["completed"] - od["created"] for od in stream.orders.values()
                          if od["completed"] is not None]) * dt
    orders_ph = (orders_done if lifelong else a.n_orders) / sim_hours

    print(_header_line(a, kernel, stream, ctx, lifelong))
    _print_completion(a, kernel, tasks_done, orders_done, T_END, lifelong)
    _print_kpi(kernel, tot, n_tasks, sim_hours, orders_ph, (lat_total, lat_drive, lat_queue),
               util, util_incl, conflict_wait)
    zone_extra = _zone_section(a, kernel, tot)
    lifelong_extra = _lifelong_section(a, kernel, tasks_done, orders_done)
    bat_extra = _battery_section(a, kernel, T_END)

    summary = dict(
        variant=a.variant, n_robots=a.n_robots, n_orders=a.n_orders, seed=a.seed,
        aisle_block=int(a.aisle_block), flow=a.flow, lanes=int(a.lanes),
        yield_rule=int(a.yield_rule), yield_events=len(kernel.yield_events), makespan_steps=int(T_END),
        speed=a.speed, dt_s=round(dt, 6),                  # v3.3 (-116): 초 단위 키의 환산 근거
        # v3.4 (-203): 회전 발자국. turn_masked = legacy 가 허용하던 (칸,회전) 중 마스크가 금지한 비율 (legacy 는 0)
        footprint=a.footprint, robot_dims=list(a.robot_dims), turn_masked=round(float(ctx.turn_masked), 4),
        # -79 (조건부, exact,front 만): 대치 상태기계 계수
        **({"standoffs": int(kernel.standoffs), "standoff_swaps": int(kernel.standoff_swaps)}
           if "front" in a.footprint or getattr(a, "standoff", False) else {}),
        **({"standoff_forced": 1} if getattr(a, "standoff", False) else {}),      # 실험 플래그 --standoff (exact + 대치 상태기계)
        tasks_per_h=round(n_tasks / sim_hours, 1),
        orders_per_h=round(orders_ph, 1),
        lead_mean_s=round(_mean(lat_total), 1),
        lead_p90_s=round(_p90(lat_total), 1),
        order_lead_mean_s=round(_mean(order_lat), 1),
        order_lead_p90_s=round(_p90(order_lat), 1),
        queue_mean_s=round(_mean(lat_queue), 1),
        drive_mean_s=round(_mean(lat_drive), 1),
        util=round(float(util), 3),
        util_incl_service=round(float(util_incl), 3),
        conflict_wait=round(float(conflict_wait), 4),
        pushed_steps=int(tot["pushed"]),
        turns_per_task=round(tot["turns"] / max(n_tasks, 1), 2),
        **(dict(heading=1, rot_steps=int(tot["rot"]), rev_steps=int(tot["rev"]),
                replan_steps=int(tot["replan"])) if kernel.heading else {}),
        **zone_extra,
        # 합성 창고 (-139): 어느 맵 세트로 잰 값인지 없으면 재현이 안 된다. 공식 맵이면 키가 안 붙는다.
        **(dict(map_dir=os.path.basename(os.path.normpath(a.map_dir))) if getattr(a, "map_dir", None) else {}),
        # 구간 대수 제한 (-193). 안 켜면 키가 안 붙어 기존 SUMMARY 와 같은 모양이다.
        # blocks 0 = 제한이 한 번도 안 걸림(헐거움). releases 가 blocks 에 육박하면 정체 면제로
        # 다 풀려 규칙이 무력한 것이다 — 블록이 너무 클 때 그렇게 된다(8×8 실측).
        **(dict(section_limit=a.section_limit, section_grid=a.section_grid,
                section_blocks=int(kernel.section_blocks),
                section_releases=int(kernel.section_releases))
           if getattr(a, "section_limit", 0) else {}),
        **(dict(order_gap=a.order_gap) if a.order_gap_arg is not None else {}),   # v1compat SUMMARY 불변
        **(dict(inbound_gap=a.inbound_gap_arg) if a.inbound_gap_arg is not None else {}),
        **lifelong_extra, **bat_extra,
        # 견적 워커용 (계약 v2.4, 키 추가만): 입고 생성 수 · 주행 거리 [m] (1칸 = CELL_M = 1.0 m). docs/견적_워커.md
        inbound_total=int(stream.n_inbound), distance_m=int(tot["cells"] * CELL_M),
        # 주행거리는 **밟은 칸**이다. drive 는 주행 틱이라 전진이 MOVE_TICKS 틱이 된 뒤로
        # 칸 수와 다르다 (-194) — 예전엔 1칸 = 1틱이라 같은 값이었다.
        **_tote_section(a, kernel, stream))
    print("[SUMMARY] " + json.dumps(summary))

    tag = _make_tag(a, kernel, lifelong)
    if a.dirflow:
        npz = os.path.join(OUT, "results", tag + "_dirflow.npz")
        np.savez_compressed(npz, dir_flow=kernel.dir_flow, visit=kernel.visit_count)
        print(f"[DIRFLOW] 저장: {os.path.basename(npz)}")
    if a.export:
        export_isaac(a, kernel, ctx)
    return summary, tag, n_tasks / sim_hours
