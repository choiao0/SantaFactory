# -*- coding: utf-8 -*-
# ============================================================
# 틱 시뮬레이터 v2 — PIBT 이동계층 (설계: docs/2026-08-31_sim_v2_틱루프_설계.md)
#
# v1(공간-시간 A* + 이벤트 루프)과 달리 매 틱 전 로봇이 PIBT로 한 칸씩
# 움직인다. 예약 장부/대기슬롯/재시도 알람 없음 — 충돌·대기는 PIBT가 해소.
#
# 흐름 모드:
#   --flow=main     (기본) 입고(inbound_buf→aisle_buf) + 출고(aisle_buf→packing).
#                   주문 = 상품 k개(1~3), 같은 통로 라인은 토트 1개로 합침,
#                   packing 주문당 1곳 고정, 주문 완료 = 전 태스크 완료.
#   --flow=v1compat B-1e 벤치마크 전용. v1과 동일한 3태스크 체인 + rng 소비 순서.
#
# 사용: python sim_v2_tasks.py [태그] [로봇수=6] [주문수=40] [시드=42] [통로차단=0|1]
#                              [--flow=main|v1compat] [--theta=<θ json 경로>]
# 환경: SIM_NO_PLOT=1 히트맵 생략, SIM_CHECK=1 매 틱 충돌 전수 검사(느림),
#       SIM_DIRFLOW=1 방향별 이동 카운트 npz 저장 (B-2 검증용)
# 출력: 콘솔 지표 + [SUMMARY] JSON + sim_v2_<태그>_r<대수>[_blk]_<flow>[_th]_heat.png
# ============================================================
import json
import os
import sys

import numpy as np

from map_loader import load_map, make_homes, CELL_M
from pibt_core import DIRS, dist_map, step

OUT = os.path.dirname(os.path.abspath(__file__))
_pos_args = [a for a in sys.argv[1:] if not a.startswith("--")]
VARIANT = _pos_args[0] if len(_pos_args) > 0 else "base"
N_ROBOTS = int(_pos_args[1]) if len(_pos_args) > 1 else 6
N_ORDERS = int(_pos_args[2]) if len(_pos_args) > 2 else 40
SEED = int(_pos_args[3]) if len(_pos_args) > 3 else 42
AISLE_BLOCK = bool(int(_pos_args[4])) if len(_pos_args) > 4 else False
FLOW = "main"
THETA_PATH = None
for _f in sys.argv[1:]:
    if _f.startswith("--flow="):
        FLOW = _f.split("=", 1)[1]
    elif _f.startswith("--theta="):
        THETA_PATH = _f.split("=", 1)[1]
assert FLOW in ("main", "v1compat"), f"알 수 없는 flow: {FLOW}"
CHECK = bool(os.environ.get("SIM_CHECK"))
DIRFLOW = bool(os.environ.get("SIM_DIRFLOW"))

SPEED = 1.0
DT = CELL_M / SPEED
SERVICE_TIME_S = 40 / 11            # v1과 동일 (docs/B0 기준선 문서 참고)
SERVICE_STEPS = round(SERVICE_TIME_S / DT)
ORDER_MEAN_GAP = 50
INBOUND_MEAN_GAP = 50               # 팀 확정 전 임시값 (주문과 동일)
N_INBOUND = N_ORDERS                # 팀 확정 전 임시값
K_LINE_P = [0.5, 0.3, 0.2]          # 주문당 상품 라인 수 {1,2,3} 분포

# ------------------------------------------------------------
# 1) 맵/로봇/비용 초기화
# ------------------------------------------------------------
FREE, st_cell, stations = load_map(OUT, AISLE_BLOCK)
H, W = FREE.shape
N_AISLE = len(stations["aisle_buf"])
N_PACK = len(stations["packing"])
N_INB_ST = len(stations["inbound_buf"])
homes = make_homes(FREE, st_cell, N_ROBOTS)

# 통행 비용 — 기본 uniform 1.0. --theta=<json>이면 from_theta(θ) 출력 (B-2).
if THETA_PATH:
    from from_theta import extract_topology, from_theta, load_theta
    _g = from_theta(FREE, extract_topology(FREE, st_cell), load_theta(THETA_PATH))
    edge_cost = _g.edge_cost.astype(np.float64)
    wait_cost = _g.wait_cost.astype(np.float64)
else:
    edge_cost = np.ones((H, W, 4), dtype=np.float64)
    wait_cost = np.ones((H, W), dtype=np.float64)

_dist_cache = {}


def dmap(goal):
    if goal not in _dist_cache:
        _dist_cache[goal] = dist_map(FREE, goal)
    return _dist_cache[goal]


_stay_cache = {}


def staymap(cell):
    """서비스 중 고정용: 현재 칸만 0, 나머지 -1 → PIBT 후보가 stay 하나뿐."""
    if cell not in _stay_cache:
        m = np.full((H, W), -1, dtype=np.int32)
        m[cell] = 0
        _stay_cache[cell] = m
    return _stay_cache[cell]


# 로봇 상태 (설계 §4) / PIBT 계급 (설계 §5)
IDLE, TO_PICK, SVC_PICK, TO_DROP, SVC_DROP, TO_HOME, FREED = \
    "IDLE", "TO_PICK", "SVC_PICK", "TO_DROP", "SVC_DROP", "TO_HOME", "FREED"
RANK = {SVC_PICK: 0, SVC_DROP: 0, TO_DROP: 1, TO_PICK: 2, TO_HOME: 3, IDLE: 3,
        FREED: 3}
NAV = (TO_PICK, TO_DROP, TO_HOME)

robots = {}
for rid in range(N_ROBOTS):
    robots[rid] = dict(pos=homes[rid], home=homes[rid], state=IDLE,
                       goal=homes[rid], task=None, svc_end=-1, waitc=0,
                       drive=0, wait=0, pushed=0, svc=0, turns=0, heading=None)

visit_count = np.zeros((H, W), dtype=int)
dir_flow = np.zeros((H, W, 4), dtype=int)   # 출발칸×방향 이동 수 (NAV만, B-2 계측)

# ------------------------------------------------------------
# 2) 주문/입고 생성 (rng 소비 순서 = 설계 §6 패리티 규칙)
# ------------------------------------------------------------
rng = np.random.default_rng(SEED)
order_times = np.cumsum(rng.exponential(ORDER_MEAN_GAP, N_ORDERS)).astype(int) + 1
if FLOW == "main":
    inbound_times = np.cumsum(
        rng.exponential(INBOUND_MEAN_GAP, N_INBOUND)).astype(int) + 1
else:
    inbound_times = np.array([], dtype=int)

task_seq = 0
waiting = []                # 배차 대기 태스크 (FIFO)
tasks_done = []
orders = {}                 # oid -> dict(created, remaining, completed)
chains = {}                 # v1compat: oid -> 남은 체인 정의
outstanding_orders = N_ORDERS
outstanding_inbound = N_INBOUND if FLOW == "main" else 0


def make_task(kind, frm_name, to_name, t, order_id):
    global task_seq
    task_seq += 1
    return dict(id=task_seq, order=order_id, kind=kind,
                frm_name=frm_name, to_name=to_name,
                frm=st_cell[frm_name], to=st_cell[to_name],
                created=t, assigned=None, completed=None)


def spawn_order(oid, t):
    if FLOW == "v1compat":
        # v1 spawn_chain과 동일한 4 draw를 도착 틱에 일괄 소비 (설계 §6)
        a = int(rng.integers(N_AISLE))
        chain = [("supply", f"induction[{int(rng.integers(2))}]", f"aisle_buf[{a}]"),
                 ("retrieve", f"aisle_buf[{a}]", f"consol[{int(rng.integers(2))}]"),
                 ("pack", None, f"packing[{int(rng.integers(5))}]")]
        chains[oid] = chain
        knd, frm, to = chains[oid].pop(0)
        waiting.append(make_task(knd, frm, to, t, oid))
        orders[oid] = dict(created=t, remaining=3, completed=None)
    else:
        k = int(rng.choice([1, 2, 3], p=K_LINE_P))
        aisles = [int(rng.integers(N_AISLE)) for _ in range(k)]   # 중복 허용
        p = int(rng.integers(N_PACK))
        uniq = list(dict.fromkeys(aisles))       # 같은 통로 라인은 토트 1개로 합침
        for a in uniq:
            waiting.append(make_task("out", f"aisle_buf[{a}]", f"packing[{p}]", t, oid))
        orders[oid] = dict(created=t, remaining=len(uniq), completed=None)


def spawn_inbound(iid, t):
    frm = f"inbound_buf[{int(rng.integers(N_INB_ST))}]"
    to = f"aisle_buf[{int(rng.integers(N_AISLE))}]"
    waiting.append(make_task("in", frm, to, t, None))


def complete_task(rb, task, t):
    """하역 서비스 만료 시 공통 처리. 체인/주문 카운터 갱신."""
    global outstanding_orders, outstanding_inbound
    task["completed"] = t
    tasks_done.append(task)
    oid = task["order"]
    if oid is None:                              # 입고 태스크
        outstanding_inbound -= 1
    else:
        od = orders[oid]
        od["remaining"] -= 1
        if FLOW == "v1compat" and chains.get(oid):
            knd, frm, to = chains[oid].pop(0)
            frm = frm or task["to_name"]         # pack은 직전 도착지에서 출발
            waiting.append(make_task(knd, frm, to, t, oid))
        if od["remaining"] == 0:
            od["completed"] = t
            outstanding_orders -= 1


def begin_service(rb, t, kind):
    rb["state"] = SVC_PICK if kind == "pick" else SVC_DROP
    rb["svc_end"] = t + SERVICE_STEPS
    rb["goal"] = rb["pos"]


def try_assign_all(t):
    """설계 §7: waiting FIFO × (IDLE ∪ FREED) 최근접 배차. 남은 FREED는 홈으로."""
    eligible = [rid for rid, rb in robots.items() if rb["state"] in (IDLE, FREED)]
    for task in list(waiting):
        if not eligible:
            break
        fr, fc = task["frm"]
        rid = min(eligible, key=lambda i: abs(robots[i]["pos"][0] - fr) +
                  abs(robots[i]["pos"][1] - fc))
        rb = robots[rid]
        rb["state"], rb["task"], rb["goal"] = TO_PICK, task, task["frm"]
        task["assigned"] = t
        waiting.remove(task)
        eligible.remove(rid)
        if rb["pos"] == rb["goal"]:              # 제자리 배차(pack 승계 등) 즉시 도킹
            begin_service(rb, t, "pick")
    for rid, rb in robots.items():
        if rb["state"] == FREED:
            rb["state"], rb["goal"] = TO_HOME, rb["home"]
            if rb["pos"] == rb["goal"]:
                rb["state"] = IDLE


# ------------------------------------------------------------
# 3) 틱 루프 (설계 §3 — pos(t) 기준 처리, step은 pos(t)→pos(t+1))
# ------------------------------------------------------------
order_i = inbound_i = 0
t = 0
_progress = [0, 0]
rids = list(robots)

while outstanding_orders + outstanding_inbound > 0:
    # (1) 주문/입고 도착 — 동일 틱은 주문(oid순) 먼저, 그다음 입고
    while order_i < N_ORDERS and order_times[order_i] <= t:
        spawn_order(order_i, t)
        order_i += 1
    while inbound_i < len(inbound_times) and inbound_times[inbound_i] <= t:
        spawn_inbound(inbound_i, t)
        inbound_i += 1

    # (2) 서비스 완료 — 전 로봇 만료 처리 후 join 판정(complete_task 내 카운터)
    for rid in rids:
        rb = robots[rid]
        if rb["state"] in (SVC_PICK, SVC_DROP) and rb["svc_end"] == t:
            if rb["state"] == SVC_PICK:
                rb["state"], rb["goal"] = TO_DROP, rb["task"]["to"]
            else:
                complete_task(rb, rb["task"], t)
                rb["state"], rb["task"] = FREED, None

    # (3) 배차
    try_assign_all(t)
    if outstanding_orders + outstanding_inbound == 0:
        break

    # (4) PIBT 한 스텝: pos(t) → pos(t+1)
    prio = sorted(rids, key=lambda r: (RANK[robots[r]["state"]],
                                       -robots[r]["waitc"], r))
    positions = {rid: robots[rid]["pos"] for rid in rids}
    dists = {}
    for rid in rids:
        rb = robots[rid]
        dists[rid] = staymap(rb["pos"]) if rb["state"] in (SVC_PICK, SVC_DROP) \
            else dmap(rb["goal"])
    new_pos = step(positions, dists, edge_cost, wait_cost, FREE, prio)

    if CHECK:
        cells = list(new_pos.values())
        assert len(cells) == len(set(cells)), f"t={t} vertex 충돌"
        for i, a in enumerate(rids):
            for b in rids[i + 1:]:
                assert not (new_pos[a] == positions[b] and
                            new_pos[b] == positions[a]), f"t={t} 스왑 {a}<->{b}"

    for rid in rids:
        rb = robots[rid]
        p0, p1 = rb["pos"], new_pos[rid]
        moved = p1 != p0
        if rb["state"] in NAV:
            visit_count[p1] += 1        # v1과 동일: 임무 주행(경로 내 대기 포함)만 집계
            if moved:
                rb["drive"] += 1
                rb["waitc"] = 0
                gd = dists[rid]
                if gd[p1] > gd[p0]:
                    rb["pushed"] += 1
            else:
                rb["wait"] += 1
                rb["waitc"] += 1
        elif rb["state"] in (SVC_PICK, SVC_DROP):
            rb["svc"] += 1
        if moved:
            d = DIRS.index((p1[0] - p0[0], p1[1] - p0[1]))
            if rb["state"] in NAV:
                dir_flow[p0[0], p0[1], d] += 1
            if rb["heading"] is not None and d != rb["heading"]:
                rb["turns"] += 1
            rb["heading"] = d
        rb["pos"] = p1
    t += 1

    # (5) 도착 감지 — pos(t+1) 기준 (이 시점의 시각 = 갱신된 t)
    for rid in rids:
        rb = robots[rid]
        if rb["pos"] != rb["goal"]:
            continue
        if rb["state"] == TO_PICK:
            begin_service(rb, t, "pick")
        elif rb["state"] == TO_DROP:
            begin_service(rb, t, "drop")
        elif rb["state"] == TO_HOME:
            rb["state"] = IDLE

    # 워치독 (v1 STALL 동일 기준: 1500틱 무진전)
    if len(tasks_done) != _progress[0]:
        _progress[0], _progress[1] = len(tasks_done), t
    elif t - _progress[1] > 1500:
        print(f"[STALL] t={t}, done={len(tasks_done)}/{task_seq}, "
              f"waiting={len(waiting)}")
        for rid, rb in robots.items():
            print(f"  robot{rid} pos={rb['pos']} state={rb['state']} "
                  f"goal={rb['goal']}")
        raise SystemExit("시뮬 정체 감지")
    assert t < 200_000, "시뮬 정체 (틱 상한 초과)"

# ------------------------------------------------------------
# 4) 지표 (설계 §8 — util은 v1 호환 정의 + 참고용 병기)
# ------------------------------------------------------------
T_END = max(tk["completed"] for tk in tasks_done)
n_tasks = len(tasks_done)
lat_total = np.array([tk["completed"] - tk["created"] for tk in tasks_done]) * DT
lat_drive = np.array([tk["completed"] - tk["assigned"] for tk in tasks_done]) * DT
lat_queue = np.array([tk["assigned"] - tk["created"] for tk in tasks_done]) * DT
sim_hours = T_END * DT / 3600
drive_tot = sum(rb["drive"] for rb in robots.values())
wait_tot = sum(rb["wait"] for rb in robots.values())
svc_tot = sum(rb["svc"] for rb in robots.values())
pushed_tot = sum(rb["pushed"] for rb in robots.values())
turns_tot = sum(rb["turns"] for rb in robots.values())
busy_v1 = drive_tot + 2 * wait_tot                # v1 호환 (대기 이중계산, 서비스 제외)
util = busy_v1 / (N_ROBOTS * T_END)
util_incl = (drive_tot + wait_tot + svc_tot) / (N_ROBOTS * T_END)
conflict_wait = wait_tot / max(busy_v1, 1)
orders_ph = N_ORDERS / sim_hours

print(f"[1] 맵={VARIANT}, {H}x{W}, 로봇 {N_ROBOTS}대, 주문 {N_ORDERS}건"
      + (f" + 입고 {N_INBOUND}건" if FLOW == "main" else "")
      + f", seed={SEED}, flow={FLOW}, 통로차단={'ON' if AISLE_BLOCK else 'OFF'}")
print(f"[2] 완료: 태스크 {n_tasks}개, makespan {T_END}틱 = {T_END*DT/60:.1f}분")
print(f"[3] 처리량: {n_tasks/sim_hours:.0f} 태스크/시간 ({orders_ph:.0f} 주문/시간)")
print(f"    대기(생성→배차): 평균 {lat_queue.mean():6.1f}s / p90 {np.percentile(lat_queue, 90):6.1f}s")
print(f"    주행(배차→완료): 평균 {lat_drive.mean():6.1f}s / p90 {np.percentile(lat_drive, 90):6.1f}s")
print(f"    총 리드타임    : 평균 {lat_total.mean():6.1f}s / p90 {np.percentile(lat_total, 90):6.1f}s")
print(f"    가동률(v1호환) {util*100:.0f}% (서비스 포함 {util_incl*100:.0f}%) / "
      f"충돌대기 {conflict_wait*100:.1f}% / 밀림 {pushed_tot}틱 / "
      f"태스크당 회전 {turns_tot/max(n_tasks,1):.1f}회")

print("[SUMMARY] " + json.dumps(dict(
    variant=VARIANT, n_robots=N_ROBOTS, n_orders=N_ORDERS, seed=SEED,
    aisle_block=int(AISLE_BLOCK), flow=FLOW, makespan_steps=int(T_END),
    tasks_per_h=round(n_tasks / sim_hours, 1),
    orders_per_h=round(orders_ph, 1),
    lead_mean_s=round(float(lat_total.mean()), 1),
    lead_p90_s=round(float(np.percentile(lat_total, 90)), 1),
    queue_mean_s=round(float(lat_queue.mean()), 1),
    drive_mean_s=round(float(lat_drive.mean()), 1),
    util=round(float(util), 3),
    util_incl_service=round(float(util_incl), 3),
    conflict_wait=round(float(conflict_wait), 4),
    pushed_steps=int(pushed_tot),
    turns_per_task=round(turns_tot / max(n_tasks, 1), 2))))

_tag = (f"sim_v2_{VARIANT}_r{N_ROBOTS}{'_blk' if AISLE_BLOCK else ''}_{FLOW}"
        f"{'_th' if THETA_PATH else ''}")
if DIRFLOW:
    npz = os.path.join(OUT, "results", _tag + "_dirflow.npz")
    np.savez_compressed(npz, dir_flow=dir_flow, visit=visit_count)
    print(f"[DIRFLOW] 저장: {os.path.basename(npz)}")

if os.environ.get("SIM_NO_PLOT"):
    sys.exit(0)

# ------------------------------------------------------------
# 5) 통행 히트맵 (v1과 동일 형식)
# ------------------------------------------------------------
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(9.5, 8.5))
hm = np.where(visit_count > 0, visit_count, np.nan)
ax.imshow(np.where(FREE, 1.0, 0.25), cmap="gray", vmin=0, vmax=1, origin="lower")
im = ax.imshow(hm, cmap="inferno", origin="lower", alpha=0.9)
plt.colorbar(im, ax=ax, shrink=0.75, label="cell visits")
st_r = [rc[0] for rc in st_cell.values()]
st_c = [rc[1] for rc in st_cell.values()]
ax.scatter(st_c, st_r, s=8, c="#27ae60", marker="s", alpha=0.6)
ax.set_title(f"sim_v2 traffic — {VARIANT} ({FLOW}), {N_ROBOTS} robots, "
             f"{N_ORDERS} orders ({n_tasks/sim_hours:.0f} tasks/h)")
plt.tight_layout()
png = os.path.join(OUT, "results", _tag + "_heat.png")
plt.savefig(png, dpi=110)
print(f"[4] 저장: {os.path.basename(png)}")
