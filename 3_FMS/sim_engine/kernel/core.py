# -*- coding: utf-8 -*-
# ============================================================
# FMS 결정 커널 — 로봇 상태머신 · 배차 · PIBT 이동 · 충전 존 복귀 · 서비스 · 지표 카운터
# (설계·틱 루프: docs/커널_시뮬_구조.md#커널-인터페이스)
#
# 시계·난수·I/O 가 없다. 셸(sim_v2_tasks.py CLI / simpy_harness.py / 앞으로의 MQTT 데몬)이
#   for task in stream.arrivals(t): k.submit_task(task)
#   k.dispatch(t)                     # (2) 서비스 만료 → on_task_completed 콜백 → (3) 배차
#   if stream.outstanding == 0: break # 셸의 종료 판단 (배차 뒤·이동 전 — 리팩터링 전 루프와 같은 위치)
#   k.move(t)                         # (4) PIBT pos(t)→pos(t+1) → (5) 존 지표·재선택 → (6) 도착 → 워치독
# 순서로 부른다. step(t) = dispatch + move 편의 메서드.
#
# 이 파일은 sim_v2_tasks.py(-143 시점)의 틱 루프를 **로직 변경 없이** 옮긴 것이다. 기준값 3개·CSV 80행이 비트 동일해야 한다.
# 반복 순서(rids, robots.items())·정렬 키·동률 규칙을 바꾸지 말 것 — 결과가 바뀐다.
#
# 배터리·충전 도크 (docs/커널_시뮬_구조.md#배터리와-충전-도크): KernelConfig.battery 가 켜졌을 때만
# SoC 를 틱 단위로 차감/충전하고 TO_CHARGE/CHARGING 상태를 쓴다. 꺼져 있으면(기본) 아래 배차 순서·반복 순서는 이전과 같다.
# ============================================================
from dataclasses import dataclass

import numpy as np

from map_loader import ROBOT_DIMS, clear_of_docks, front_swing, park_slots, zone_cells
from pibt.geometry import configure as configure_footprint
from pibt.geometry import ban_on, footprint_flags, front_cells, front_swing_on
from pibt.liveness import WAIT_ESC_GRACE
from pibt_core import (DIRS, MOVE_TICKS, REV_TICKS, TURN_COST, TURN_TICKS, Replanner, Stagnation, candidates_h,
                       dist_map, dist_map_h, occupied, stay_map_h, step,
                       step_h, swing_cells, valid_state, wait_bias)

from .battery import BatteryMixin
from .metrics import MetricsMixin
from .states import (CHARGING, FREED, HOLD, IDLE, NAV, ON_TASK, PARKABLE, RANK, SERVICE,
                     SVC_DROP, SVC_PICK, TO_CHARGE, TO_DROP, TO_HOME, TO_PICK)

class StallError(RuntimeError):
    """워치독(stall_ticks 무진전). str(e) = 진단 덤프 텍스트 ([STALL] 줄 + 로봇 상태 + 후보 덤프 + 최근 이력)."""


MAX_TOTES_PER_TRIP = 6        # 선반형 AMR 3단 × 2 토트 (-177). 이 수를 넘는 주문은 여러 왕복으로(2026-09-14, 이전엔 제외)
SECTION_RELEASE = 16          # 이 틱 넘게 정체한 로봇은 구간 정원에서 면제 (-193). 재계획
                              # -194 에서 1칸이 MOVE_TICKS 틱이 되며 틱이 잘아져 8 → 16.
                              # 문턱(REPLAN_AFTER)과 같은 값 — 그 시점이면 이미 우회를 시도했다
SLOT_ENTRY_COST = 1.5         # 주차 칸으로 들어가는 이동 1칸에 더하는 비용 (-281). 칸 두 개만 지나도 옆 통로로 도는 회전 2번
                              # (2 × 1.25)보다 비싸져, 안쪽 칸으로 가는 로봇이 주차 칸 줄을 통로 삼아 서 있는 로봇을 밀지 않는다.
                              # 3.0 은 후진(× REVERSE_FACTOR)으로 제 칸에 들어가는 값이 12 가 되어, 등을 돌린 로봇이 앞으로
                              # 나갔다 되돌아오기를 한 시간 반복했다(15대). est_20 12·15대 × 시드 4개: 존 복귀 대기 −50 %·−75 %,
                              # 처리량·리드타임은 시드 흔들림 안


def slot_entry_cost(edge_cost, slots, extra=SLOT_ENTRY_COST):
    """주차 칸으로 들어가는 간선에 extra 를 더한 사본. 전진은 edge_cost[이웃, 칸 쪽 방향], 후진은 같은 값 × REVERSE_FACTOR
    를 읽으므로 한 자리에 더하면 둘 다 비싸진다. 칸에서 나가는 간선은 그대로 — 주차한 로봇은 제값에 나간다."""
    out = np.array(edge_cost, dtype=np.float64, copy=True)
    H, W = out.shape[:2]
    for r, c in slots:
        for h, (dr, dc) in enumerate(DIRS):
            nr, nc = r - dr, c - dc
            if 0 <= nr < H and 0 <= nc < W:
                out[nr, nc, h] += extra
    return out


@dataclass
class KernelConfig:
    heading: bool = True          # 헤딩 모델(기본, 계약 v2). False = 칸 모델(점로봇)
    zone: bool = True             # 충전 존 복귀 (zone_mask 가 None 이면 자동 False)
    theta: bool = False           # θ 비용 사용 여부 — 칸 모델 거리장이 가중(True)/BFS(False) 로 갈린다
    check: bool = False           # 매 틱 점유 겹침·스왑 전수 검사 (SIM_CHECK)
    dock_prio: bool = True        # 라이브니스 장치 ⑤ 도킹 칸 이탈 최우선 (SIM_NO_DOCK_PRIO 로 끔)
    export: bool = False          # Isaac 내보내기용 틱 로그 기록 (SIM_EXPORT_ISAAC)
    service_steps: int = 4        # 도킹 서비스 틱 (40/11 s ÷ DT)
    capacity: int = 1             # 출고 왕복당 토트 수
    svc_per_tote: int = 0         # 픽업·하역 각각 토트당 추가 틱
    yield_rule: bool = False      # 헤딩 정면 조우 양보
    yield_ticks: int = 40         # 양보 임시 목표 유지 상한 (-194: 틱이 잘아져 20 → 40)
    yield_after: int = 16         # 이 틱 이상 실제로 막힌 정면 조우만 양보 (-194: 8 → 16)
    turn_ticks: int = TURN_TICKS  # 90° 회전에 쓰는 틱 (실행)
    move_ticks: int = MOVE_TICKS  # 전진 1칸에 쓰는 틱 (실행, -194)
    rev_ticks: int = REV_TICKS    # 후진 1칸에 쓰는 틱 (계약 v3.15, -250: MOVE_TICKS -> 12).
                                  # 근거·출처는 geometry.REV_TICKS 주석. v3.14 로 되돌리려면 --rev-ticks=4.
    ban_release: int = 160        # 금지 조합표(-277, footprint …,ban)에서 풀어 줄 정체 틱. 코를 맞댄 1차선은 둘 다 못 돌아
                                  # 후진·전진을 되풀이한다(base 2 40 42 1 STALL). 160틱 ≈ 44 s(0.9 m/s). 정체(stag)는 포장대 줄
                                  # 대기에도 쌓여 낮추면 좁은 회전이 되살아난다 — est_18 10대 금지 회전 32틱 9.5 % · 64 7.6 % ·
                                  # 160 2.9 %, 기준 세트 40행 STALL 은 셋 다 0, 처리량 평균 −2.9 · −5.0 · −7.7 %
    replan_max_extra: int = 0     # 정체 재계획 우회 추가 비용 상한 [칸] (-247). 0 = 없음 -> 비트 동일.
                                  # 없으면 반경 3 안의 로봇 하나 때문에 +200칸 우회를 받고,
                                  # stag 는 평소 거리장으로 재이므로 그 내내 안 풀린다 (liveness.REPLAN_MAX_EXTRA)
    hd_after: int = 16            # -79 대치(standoff) 감지: 같은 칸을 다투는 두 로봇이 둘 다 이 틱 이상 무진전 (v3.9 부터 헤딩 기본; -194 다틱 후 4 → 16)
    hd_timeout: int = 80          # -79 대치 상한(틱): 넘으면 역할 교대 1회, 그래도 넘으면 해제. V2: 240 → 80 (교대 전엔 매 틱 재판정, R5)
    station_calm: bool = False    # 서비스·충전 중인 로봇 몸에 막히면(목표 칸·최선 수) 대기 상승 없이 기다린다 (-281, 계약 v3.19 헤딩 main 기본 True —
                                  # 호출자가 켠다: sim_v2 --no-station-calm, fms_core). legacy 는 False(v3.3 비트 동일)
    standoff: bool = False        # 대치 상태기계 V2 (-79). 계약 v3.9 부터 헤딩 main exact·exact,front 기본 True(호출자가 켠다: sim_v2 --no-standoff, fms_core). legacy 는 False(양보 v1, v3.3 비트 동일)
    # 회전 발자국 (-203, 계약 v3.4). footprint: "legacy"(v3.3 비트 동일) / "exact"(0.1 m 지도 정적 회전 마스크)
    # / "exact,front"(+ 앞 2칸 축 규칙·양보 v2 — 소싸움 미해결, 인자로만). 마스크 배열은 FmsKernel(turn_mask=) 로 따로 받는다.
    footprint: str = "legacy"
    robot_dims: tuple = ROBOT_DIMS  # 구동축 앞·뒤·폭 [m] — 마스크·앞 스윙 판정·Isaac 내보내기 치수
    section_limit: int = 0        # 접속행 구간별 동시 진입 대수 상한 (0 = 끔, -193)
    dock_clear: int = 3           # 장치 ⑤ 유지 거리 (체비쇼프, 로봇 길이)
    stall_ticks: int = 3000       # 워치독: 이 틱 동안 완료 무변화 → StallError (-194: 1500 → 3000)
    stall_warn_only: bool = False # 고정 시간 실행: 무진전은 기록하고 계속 (유한 모드는 기존 StallError)
    trace_len: int = 12           # STALL 덤프용 최근 틱 이력 길이
    # 배터리·충전 도크 (-145 §2-1). battery=False 면 아래는 전부 무시.
    battery: bool = False
    dock_cells: tuple = ()        # 충전 도크 칸 (r, c) — stations.json charger[0..k)
    soc_init: tuple = ()          # 로봇별 초기 SoC 0~1 (셸이 시드로 뽑아 넘김)
    drain_drive: float = 0.0      # 주행·회전 1틱 소모 (SoC 비율)
    drain_idle: float = 0.0       # 정지(대기·서비스·유휴) 1틱 소모
    charge_rate: float = 0.0      # 충전 1틱 회복
    soc_low: float = 0.20         # 강제 충전 (배차 제외)
    soc_go: float = 0.80          # 유휴 기회 충전 진입
    soc_leave: float = 0.95       # 충전 종료
    soc_yield: float = 0.50       # 강제 충전 로봇에 도크를 내주는 최소 SoC (퇴거 대상)


class FmsKernel(BatteryMixin, MetricsMixin):
    def __init__(self, free, st_cell, edge_cost, wait_cost, homes, n_robots, cfg,
                 zone_mask=None, on_task_completed=None, lane_dir=None, sec_map=None, turn_mask=None):
        # 회전 발자국 설정은 모듈 전역(pibt.geometry) — Replanner/HGraph 를 만들기 전에 넣는다 (-203).
        fp = footprint_flags(cfg.footprint)                                     # front = 4칸, front_2cell = 2칸; pitch 게이팅은 geometry (-79)
        configure_footprint(turn_mask if not fp["legacy"] else None,
                            fp["front_swing"], front_diag=fp["front_diag"],
                            robot_dims=cfg.robot_dims, ban=fp["ban"])            # ban = 금지 조합표 거부 (-277)
        self.free, self.st_cell = free, st_cell
        self.H, self.W = free.shape
        self.edge_cost, self.wait_cost = edge_cost, wait_cost
        self.cfg = cfg
        assert 1 <= cfg.capacity <= MAX_TOTES_PER_TRIP and cfg.svc_per_tote >= 0, \
            f"capacity 1~{MAX_TOTES_PER_TRIP}, svc_per_tote >= 0: {cfg.capacity}, {cfg.svc_per_tote}"
        self.heading = cfg.heading
        self.zone = bool(cfg.zone and zone_mask is not None)
        self.zone_mask = zone_mask if self.zone else None
        self.zone_cells = zone_cells(free, zone_mask) if self.zone else []
        self.park_slots = park_slots(free, zone_mask) if self.zone else []      # 안쪽부터 (-281)
        self.lane_dir = lane_dir
        # 구간 대수 제한 (-193). 맵이 안 주면(sec_map None) 또는 정원 0 이면 장치가 꺼진다.
        self.sec_map = sec_map if cfg.section_limit > 0 else None
        self.section_blocks = self.section_releases = 0
        self.ban_releases = 0        # 금지 조합표에서 풀린 (로봇 × 틱) — 교착 탈출 안전판이 쓰인 양 (-277)
        self.zone_stats = dict(wait=0, retargets=0, degraded=0, slots_full=0, swaps=0, occ=[])   # 구현 설계 §4. occ = 틱별 존 안 로봇 수
        self.on_task_completed = on_task_completed
        self.station_cells = frozenset(st_cell.values())
        # 거리장 가중은 틱 수가 아니라 전진 1칸 대비 배율이다 — edge_cost 기준이 1.0 이라
        # 틱 수를 그대로 넣으면 회전이 전진의 turn_ticks 배가 된다 (-194, geometry.TURN_COST).
        assert cfg.move_ticks >= 1 and cfg.turn_ticks >= 1 and cfg.rev_ticks >= 1, \
            f"move_ticks/turn_ticks/rev_ticks 는 1 이상: {cfg.move_ticks}, {cfg.turn_ticks}, {cfg.rev_ticks}"
        self.turn_cost = cfg.turn_ticks / cfg.move_ticks
        self.warnings = []                      # 초기화 중 경고 문구 (셸이 출력)
        self._init_battery(free, n_robots)
        if self.heading and self.park_slots:
            self.edge_cost = edge_cost = slot_entry_cost(edge_cost, self.park_slots)
        # 거리장 캐시 (θ 는 실행 중 고정이라 무효화 불필요)
        self._dist_cache, self._dist_cache_h, self._stay_cache = {}, {}, {}
        self._stag = Stagnation()               # 헤딩: 거리 개선 없는 연속 틱 (우선순위·대기 상승·재계획)
        self._replan = (Replanner(free, edge_cost, self.turn_cost, max_extra=cfg.replan_max_extra)
                        if self.heading else None)
        self._trace = []                        # STALL 진단용 링버퍼 (t, rid -> (상태, busy, 액션))
        self.stall_warning_ticks = []            # 고정 시간 모드 무진전 경고 시각(계속 실행)
        self._init_robots(homes, n_robots)
        if self.heading:
            self._init_headings(free, homes)
            self._check_goal_spacing(st_cell, homes, n_robots)
        self.visit_count = np.zeros((self.H, self.W), dtype=int)
        self.wait_count = np.zeros((self.H, self.W), dtype=int)    # NAV 제자리 대기 — checks/wait_map.py
        self.dir_flow = np.zeros((self.H, self.W, 4), dtype=int)   # 출발칸×방향 이동 수 (NAV만, B-2 계측)
        self.waiting = []                       # 배차 대기 태스크 (FIFO)
        self.tasks_done = []
        self.trips = 0                            # 완료된 출고 왕복 수
        self.yield_events = []                    # 정면 조우 진단 이벤트 (양보 v2 legacy / -79 대치 "standoff")
        self.standoffs = self.standoff_swaps = 0  # -79 대치 수·역할 교대 수 (SUMMARY, exact,front 만)
        self.standoff_ticks = 0                   # -229 대치에 묶인 로봇·틱 합 (건수와 달리 "얼마나 오래"를 잰다)
        self.stag_robot_ticks = 0                 # 물리 팀 대안 지표: stag >= hd_after 인 로봇·틱 합.
        self.stag_robot_ticks_all = 0             # 같은 값, NAV 게이트 없이 (두 해석 차이를 보이려고)
        self.n_submitted = 0
        self._progress = [0, 0]                 # (완료 수, 그때 t) — 워치독
        self.export_log = {}
        if cfg.export:
            for rid in self.rids:               # t=0 초기 자세
                rb = self.robots[rid]
                self.export_log[rid] = [(0, rb["pos"][0], rb["pos"][1], rb["h"], "wait")]

    def _init_battery(self, free, n_robots):
        """배터리·충전 도크 (-145 §2). 도크는 주차 후보(zone_cells)에서 제외 — 초기 배치(homes)는 셸이 그대로 둔다(§2-5)."""
        cfg = self.cfg
        self.battery = bool(cfg.battery)
        self.docks = [tuple(d) for d in cfg.dock_cells] if self.battery else []
        self.dock_owner = {d: None for d in self.docks}
        if self.battery:
            assert self.docks, "배터리 모드: 도크 칸이 없음"
            assert all(free[d] for d in self.docks), f"도크 칸이 통행 불가: {[d for d in self.docks if not free[d]]}"
            assert len(cfg.soc_init) == n_robots, f"soc_init {len(cfg.soc_init)} != 로봇 {n_robots}"
            dock_set = set(self.docks)
            self.zone_cells = [rc for rc in self.zone_cells if rc not in dock_set]
            self.park_slots = clear_of_docks(self.park_slots, self.docks)    # 셸의 초기 배치와 같은 규칙 (-281)
        self.bat_stats = dict(events=0, charging=0, dock_wait=0, evictions=0, soc_min=1.0, empty=0)

    def _init_robots(self, homes, n_robots):
        """로봇 상태 dict (홈에서 IDLE). 배터리면 초기 SoC 는 cfg.soc_init."""
        cfg = self.cfg
        self.robots = {}
        for rid in range(n_robots):
            self.robots[rid] = dict(pos=homes[rid], home=homes[rid], state=IDLE,
                                    goal=homes[rid], task=None, svc_end=-1, waitc=0,
                                    drive=0, cells=0, wait=0, pushed=0, svc=0, turns=0, heading=None,
                                    h=None, busy=0, busy_move=0, swing=set(), rot=0, rev=0, replan=0,
                                    turns_idle=0, goal_prev=None, goal_t=0, idle_moves=0, leave_from=None,
                                    yield_peer=None, yield_target=None, yield_until=-1, yield_hold=False,
                                    hd_peer=None, hd_role=None, hd_until=-1, hd_swapped=False, hd_t0=-1, swing_soft=set(),
                                    turn_pair=None, soc=1.0, charge_n=0, chg=0, soc_empty=0)
            if self.battery:
                self.robots[rid]["soc"] = float(cfg.soc_init[rid])
        if self.battery:
            self.bat_stats["soc_min"] = min(rb["soc"] for rb in self.robots.values())
        self.rids = list(self.robots)

    def _init_headings(self, free, homes):
        """초기 방향: 홈에서 valid(뒤 칸 free)하고 타 로봇 점유와 안 겹치는 첫 방향 (결정론적)."""
        taken = set()
        for rid in self.rids:
            r0, c0 = homes[rid]
            for h in range(4):
                s = (r0, c0, h)
                if valid_state(free, s) and not (set(occupied(s)) & taken):
                    self.robots[rid]["h"] = h
                    taken |= set(occupied(s))
                    break
            assert self.robots[rid]["h"] is not None, f"robot{rid} 홈 {homes[rid]}: 유효한 초기 방향 없음"

    def _check_goal_spacing(self, st_cell, homes, n_robots):
        """목표(도킹) 칸 간격 점검: 2칸 차체는 목표 칸 간 체비쇼프 거리 < 3이면 도착 자세에 따라 차체가 겹칠 수
        있다(핑퐁 진동 원인). 존이면 홈은 설계상 간격 2(동적 목표)라 점검에서 제외."""
        goal_cells = list(dict.fromkeys(list(st_cell.values()) + ([] if self.zone else list(homes[:n_robots]))))
        close = [(a, b) for i, a in enumerate(goal_cells) for b in goal_cells[i + 1:]
                 if max(abs(a[0] - b[0]), abs(a[1] - b[1])) < 3]
        if close:
            self.warnings.append(f"[WARN] 헤딩 모델: 목표 칸 간격 <3인 쌍 {len(close)}개 (차체 겹침 가능) 예: {close[:3]}")

    # ------------------------------------------------------------
    # 거리장
    # ------------------------------------------------------------
    def dmap(self, goal):
        """칸 모델 거리장 캐시. θ면 가중 다익스트라, 아니면 비가중 BFS (기본 경로 불변)."""
        if goal not in self._dist_cache:
            self._dist_cache[goal] = dist_map(self.free, goal, self.edge_cost if self.cfg.theta else None)
        return self._dist_cache[goal]

    def dmap_h(self, goal):
        """헤딩 모델 거리장 (H,W,4): (칸,방향) 그래프 위 가중 다익스트라 (θ 없으면 비용 1.0)."""
        if goal not in self._dist_cache_h:
            dm = dist_map_h(self.free, goal, self.edge_cost, self.turn_cost)
            assert dm.max() >= 0, f"목표 {goal}에 유효한 도착 방향이 없음"
            self._dist_cache_h[goal] = dm
        return self._dist_cache_h[goal]

    def staymap(self, cell):
        """서비스 중 고정용(칸 모델): 현재 칸만 0, 나머지 -1 → PIBT 후보가 stay 하나뿐."""
        if cell not in self._stay_cache:
            m = np.full((self.H, self.W), -1, dtype=np.int32)
            m[cell] = 0
            self._stay_cache[cell] = m
        return self._stay_cache[cell]

    # ------------------------------------------------------------
    # 태스크·배차·존
    # ------------------------------------------------------------
    def submit_task(self, task):
        self.waiting.append(task)
        self.n_submitted += 1

    def _begin_service(self, rb, t, kind):
        rb["state"] = SVC_PICK if kind == "pick" else SVC_DROP
        n_totes = 1 + len(rb["task"].get("riders", ()))
        rb["svc_end"] = t + self.cfg.service_steps + n_totes * self.cfg.svc_per_tote
        rb["goal"] = rb["pos"]

    def _body_cells(self, rb):
        """로봇이 지금 점유한 칸: 헤딩 모델은 앞축+뒤 칸, 칸 모델은 한 칸."""
        if self.heading and rb["h"] is not None:
            return occupied((rb["pos"][0], rb["pos"][1], rb["h"]))
        return (rb["pos"],)

    def zone_goal(self, rid):
        """충전 존 복귀 목표. 주차 칸(park_slots)이 있으면 안쪽부터 첫 빈 칸 (S15P21A106-281) — 예약 칸(타 로봇의
        존 안 목표와 그 체비쇼프<2 이웃)이나 타 로봇 몸이 걸친 칸은 건너뛴다. 칸이 다 차면(slots_full) 예전 규칙
        (구현 설계 §3): 존 free 칸 − 예약 칸 중 맨해튼 최근접 → 후보 없음 → 예약 무시(degraded) → 그래도 없으면 고정 홈.
        예전 규칙만 쓰면 모두 입구 쪽 모서리에 1칸 간격으로 붙어 뒤에 온 로봇이 그 사이를 비집고 들어갔다."""
        rb = self.robots[rid]
        reserved, bodies = self._zone_reservations(rid)
        if self.park_slots:
            for rc in self.park_slots:
                if rc not in reserved and rc not in bodies:
                    return rc
            self.zone_stats["slots_full"] += 1
        pr, pc = rb["pos"]
        key = lambda rc: (abs(rc[0] - pr) + abs(rc[1] - pc), rc[1], rc[0])
        cand = [rc for rc in self.zone_cells if rc not in reserved and rc not in bodies]
        if not cand:
            self.zone_stats["degraded"] += 1
            cand = [rc for rc in self.zone_cells if rc not in bodies]
            if not cand:
                return rb["home"]
        return min(cand, key=key)

    def _zone_reservations(self, rid):
        """rid 를 제외한 타 로봇의 (존 안 목표 + 체비쇼프<2 이웃 예약 칸, 몸 칸) 집합."""
        zone_mask = self.zone_mask
        reserved, bodies = set(), set()
        for o, ob in self.robots.items():
            if o == rid:
                continue
            # 충전 가는/중인 로봇의 도크(존 안)와 이웃도 예약 — 주차 로봇이 도킹 자세를 막지 않게 (-145 §2-5)
            if ob["state"] in (TO_HOME, IDLE, TO_CHARGE, CHARGING) and zone_mask[ob["goal"]]:
                gr, gc = ob["goal"]
                reserved.update((gr + dr, gc + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))
            bodies.update(self._body_cells(ob))
        return reserved, bodies

    def _try_assign_all(self, t):
        """설계 §7: waiting FIFO × (IDLE ∪ FREED) 최근접 배차. 배터리 모드에서 SoC < soc_low 인 로봇은 후보에서 뺀다."""
        robots = self.robots
        eligible = [rid for rid, rb in robots.items() if rb["state"] in (IDLE, FREED) and not self._needs_charge(rb)]
        for task in list(self.waiting):
            if not eligible:
                break
            if task not in self.waiting:             # 앞 태스크의 동승 토트로 이미 적재됨
                continue
            fr, fc = task["frm"]
            rid = min(eligible, key=lambda i: abs(robots[i]["pos"][0] - fr) + abs(robots[i]["pos"][1] - fc))
            rb = robots[rid]
            rb["state"], rb["task"], rb["goal"] = TO_PICK, task, task["frm"]
            task["assigned"] = t
            self.waiting.remove(task)
            if task["kind"] == "out" and self.cfg.capacity > 1:
                riders = [tk for tk in self.waiting
                          if tk["kind"] == "out" and tk["frm"] == task["frm"]][:self.cfg.capacity - 1]
                for tk in riders:
                    tk["assigned"] = t
                    tk["to"], tk["to_name"] = task["to"], task["to_name"]
                    self.waiting.remove(tk)
                if riders:
                    task["riders"] = riders
            eligible.remove(rid)
            if rb["pos"] == rb["goal"]:              # 제자리 배차(pack 승계 등) 즉시 도킹
                self._begin_service(rb, t, "pick")

    def _send_freed_home(self):
        """남은 FREED는 홈으로 (존: 존 내 최근접 빈 칸, 도착하면 그 칸이 새 홈)."""
        for rid, rb in self.robots.items():
            if rb["state"] == FREED:
                rb["state"] = TO_HOME
                rb["goal"] = self.zone_goal(rid) if self.zone else rb["home"]
                if self.zone:
                    rb["home"] = rb["goal"]
                if rb["pos"] == rb["goal"]:
                    rb["state"] = IDLE

    # ------------------------------------------------------------
    # 틱 — dispatch(t) → [셸 종료 판단] → move(t)
    # ------------------------------------------------------------
    def dispatch(self, t):
        """(2) 서비스 완료 — 전 로봇 만료 처리, 하역 완료는 on_task_completed 콜백(후속 태스크 즉시 접수).
        (배터리) 충전 종료 → 강제 충전. (3) 배차. (배터리) 기회 충전. FREED → 홈."""
        self._finish_services(t)
        if self.battery:
            self._charge_release()
            self._charge_forced()
            self._unpark_docks()
        self._try_assign_all(t)
        if self.battery:
            self._charge_opportunistic()
        self._send_freed_home()

    def _finish_services(self, t):
        """(2) 서비스 만료: 픽업 완료 → TO_DROP, 하역 완료 → 태스크 완료(콜백으로 후속 태스크 접수) → FREED."""
        for rid in self.rids:
            rb = self.robots[rid]
            if rb["state"] in SERVICE and rb["svc_end"] == t:
                if rb["state"] == SVC_PICK:
                    rb["state"], rb["goal"] = TO_DROP, rb["task"]["to"]
                else:
                    self._complete_drop(rb, t)

    def _complete_drop(self, rb, t):
        task = rb["task"]
        for tote in (task, *task.get("riders", ())):
            tote["completed"] = t
            self.tasks_done.append(tote)
            if self.on_task_completed is not None:
                for follow in self.on_task_completed(tote, t) or ():
                    self.submit_task(follow)
        if task["kind"] == "out":
            self.trips += 1
        rb["state"], rb["task"] = FREED, None

    def move(self, t):
        """(4) PIBT 한 스텝 pos(t)→pos(t+1), (5) 존 지표·재선택, (배터리) 틱 소모, (6) 도착 감지(시각 t+1), 워치독."""
        robots, rids = self.robots, self.rids
        before = None
        if self.zone or self.battery:
            before = {rid: (robots[rid]["pos"], robots[rid]["h"], robots[rid]["busy"]) for rid in rids}
        if self.heading:
            self._tick_heading(t)
        else:
            self._tick_cell(t)
        t1 = t + 1
        if self.zone:
            self._zone_metrics(before)
            self._zone_retarget()
        if self.battery:
            self._battery_tick(before)              # 도착 판정 전 — 도착한 틱은 주행 소모, 충전은 다음 틱부터
        self._detect_arrivals(t1)
        self._watchdog(t1)
        assert t1 < 200_000, "시뮬 정체 (틱 상한 초과)"

    def _zone_metrics(self, before):
        """존 지표 (구현 설계 §4): 존 안 복귀 대기 / 비임무 밀림 이동 / 동시 주차."""
        robots, zone_mask, zs = self.robots, self.zone_mask, self.zone_stats
        for rid in self.rids:
            rb = robots[rid]
            p0, h0, _ = before[rid]
            if rb["state"] == TO_HOME and rb["pos"] == p0 and rb["h"] == h0 and zone_mask[p0]:
                zs["wait"] += 1
            elif rb["state"] in (IDLE, FREED) and rb["pos"] != p0:
                rb["idle_moves"] += 1
        zs["occ"].append(sum(1 for rb in robots.values() if zone_mask[rb["pos"]]))

    def _zone_retarget(self):
        """재선택 (구현 설계 §3): 목표 칸에 다른 로봇이 IDLE로 주차했으면 다시 고른다. 밀려난 주차 로봇 둘이 서로의
        칸에 서 있으면 칸을 맞바꾼다 (-281) — 막다른 줄에서는 서로 비켜 지나갈 수 없어 한 시간 내내 오갔다(15대 시드 2)."""
        robots = self.robots
        off = {robots[rid]["pos"]: rid for rid in self.rids
               if robots[rid]["state"] == IDLE and robots[rid]["pos"] != robots[rid]["goal"]}
        for cell, a in off.items():
            b = off.get(robots[a]["goal"])
            if b is not None and b != a and robots[b]["goal"] == cell:
                for rid in (a, b):
                    robots[rid]["goal"] = robots[rid]["home"] = robots[rid]["pos"]
                self.zone_stats["swaps"] += 1
        parked = {}
        for o, ob in robots.items():
            if ob["state"] == IDLE:
                for rc in self._body_cells(ob):
                    parked[rc] = o
        for rid in self.rids:
            rb = robots[rid]
            if rb["state"] == TO_HOME and rb["pos"] != rb["goal"] and parked.get(rb["goal"], rid) != rid:
                rb["goal"] = rb["home"] = self.zone_goal(rid)
                self.zone_stats["retargets"] += 1

    def _detect_arrivals(self, t1):
        """(6) 도착 감지 — pos(t+1) 기준."""
        for rid in self.rids:
            rb = self.robots[rid]
            if rb["pos"] != rb["goal"]:
                continue
            if rb["state"] == TO_PICK:
                self._begin_service(rb, t1, "pick")
            elif rb["state"] == TO_DROP:
                self._begin_service(rb, t1, "drop")
            elif rb["state"] == TO_HOME:
                rb["state"] = IDLE
            elif rb["state"] == TO_CHARGE:
                rb["state"] = CHARGING

    def _watchdog(self, t1):
        """워치독 (v1 STALL 동일 기준: stall_ticks 무진전). 고정 시간 모드(stall_warn_only)에서만 "대기 큐가 비고 임무 중
        로봇이 없으면 할 일이 없는 것"을 진전으로 본다 (-145 §2-7: 한가한 구간·집단 충전). 유한 모드는 옛 규칙 그대로 —
        이 조건은 유한 모드에서도 첫 도착 전(도착 틱 ≥ 1)에 참이 되므로 게이트 없이 두면 한가한 부하(간격 ≥ 1000)의
        STALL 시각·유무가 v2.1 과 달라진다 (2026-09-06 검토에서 재현)."""
        if len(self.tasks_done) != self._progress[0] or \
                (self.cfg.stall_warn_only and not self.waiting
                 and not any(rb["state"] in ON_TASK for rb in self.robots.values())):
            self._progress[0], self._progress[1] = len(self.tasks_done), t1
        elif t1 - self._progress[1] > self.cfg.stall_ticks:
            if self.cfg.stall_warn_only:
                self.stall_warning_ticks.append(t1)
                self._progress[1] = t1
            else:
                raise StallError(self._stall_dump(t1))

    def step(self, t):
        self.dispatch(t)
        self.move(t)

    # ------------------------------------------------------------
    # 이동 — 헤딩 모델
    # ------------------------------------------------------------
    def _tick_heading(self, t):
        """헤딩 모델 한 틱 (설계 2026-09-02 §7). 서비스 중·회전 중 로봇은 stay 고정,
        회전 중 스윙 칸은 extra 점유로 넘긴다. 지표: 회전 틱은 rot에 (wait와 분리)."""
        robots, rids, free, cfg = self.robots, self.rids, self.free, self.cfg
        self._stamp_goal_changes(t)
        if cfg.dock_prio:
            self._update_dock_leave()
        states = {rid: (robots[rid]["pos"][0], robots[rid]["pos"][1], robots[rid]["h"]) for rid in rids}
        standoff = front_swing_on() or cfg.standoff   # -79: 대치 상태기계 V2 — v3.9 부터 exact 기본(cfg.standoff), exact,front 는 항상. legacy 는 양보 v1
        extra = {rid: robots[rid]["swing"] for rid in rids if robots[rid]["busy"] > 0}
        # 회전 진행 중인 로봇의 soft 칸: 다른 로봇이 축을 들이지 못하게 이번 틱 예약으로 넘긴다 (-79, 다틱 회전)
        # 두 회전 로봇의 soft 칸이 겹치면 낮은 rid 가 주인(결정적) — 제3자에게는 누구든 똑같이 막힌다 (답신 11 §4)
        soft_hold = {cell: rid for rid in sorted(rids, reverse=True) if robots[rid]["busy"] > 0
                     for cell in robots[rid]["swing_soft"]}
        # 회전 진행 중인 로봇 (-277): 금지 조합표가 켜졌으면 step_h 가 그 기준 금지 자리로 남을 못 들인다
        turning = {rid: robots[rid]["turn_pair"] for rid in rids
                   if robots[rid]["busy"] > 0 and robots[rid].get("turn_pair")}
        if cfg.yield_rule and not standoff:
            self._refresh_yields(t, states)
        if standoff:
            self._refresh_standoffs(t, states, extra)
        prio = self._priority_h(t)
        dists = self._dists_h(t, states, extra)
        if standoff:
            if self._detect_standoffs(t, states, prio, dists, extra, soft_hold):
                prio = self._priority_h(t)
                dists = self._dists_h(t, states, extra)         # 역할(L = 기본 거리장)이 이번 틱 바뀐 로봇
            # -229: 이번 틱 대치에 묶인 로봇 수를 더한다(감지 뒤라 이번 틱 새 대치도 센다). standoffs 는 건수라
            # 짧은 대치 100건과 긴 대치 1건을 구분 못 한다 — 묶인 시간이 처리량에 닿는 몫이다.
            self.standoff_ticks += sum(1 for rid in rids if robots[rid]["hd_peer"] is not None)
        elif cfg.yield_rule and self._detect_headons(t, states, prio, dists):
            prio = self._priority_h(t)
            dists = self._dists_h(t, states, extra)
        # 대치 상태기계 없이도 잴 수 있는 대리 지표(물리 팀 t3-27). 대치 감지의 **입력**이라 상위 집합이다 —
        # 대치는 "정체한 두 로봇이 같은 칸을 다툰다" 이므로, 정체 로봇·틱은 그보다 크거나 같다.
        # 게이트는 감지와 같은 state ∈ NAV (§2-2 A). _all 은 게이트를 뺀 값 — 두 해석의 차이를 재려고 같이 센다.
        hd = cfg.hd_after
        self.stag_robot_ticks += sum(1 for rid in rids
                                     if robots[rid]["state"] in NAV and self._stag.get(rid) >= hd)
        self.stag_robot_ticks_all += sum(1 for rid in rids if self._stag.get(rid) >= hd)
        forbid = forbid_axle = None
        if standoff:
            # -79 V2 (R4): 대치 중인 둘도 대기 상승은 정상 — V1 의 "둘 다 calm" 은 후진(×3)보다 대기를 싸게 만들어 이기는 쪽까지
            # 세웠다(exp16 실측: 한 쌍이 240틱 교대 83회). 지는 쪽의 전진·후진 핑퐁은 forbid(이기는 쪽 wish 재진입 금지)가 막는다.
            # (R1) 인내: 회전 중 로봇의 임시 예약에만 막힌 로봇은 이번 틱 상승 0 — 헛회전 대신 몇 틱 기다린다 (시드 42 위상 잠금).
            calm = self._patient(states, dists, extra, soft_hold)
            forbid, forbid_axle = self._standoff_forbid(states, dists)
        else:
            calm = {rid for rid in rids if robots[rid]["yield_peer"] is not None}        # legacy: 비켜 주는 쪽만 상승 없음
        if cfg.station_calm:
            calm = set(calm) | self._goal_held()
        bias = {rid: 0.0 if rid in calm else wait_bias(self._stag.get(rid)) for rid in rids}
        # 정체가 SECTION_RELEASE 틱을 넘은 로봇은 정원에서 푼다. 전면 분할처럼 우회로가
        # 구간 밖에 없을 때 순환 대기를 깨는 마지막 안전판이다 (-193).
        sec_free = ({rid for rid in rids if self._stag.get(rid) > SECTION_RELEASE}
                    if cfg.section_limit else ())
        # 금지 조합표에서 푸는 로봇 (-277): 오래 정체한 로봇만 좁은 회전을 허락한다 — 구간 정원의 sec_free 와 같은 안전판
        ban_free = ({rid for rid in rids if self._stag.get(rid) > cfg.ban_release} if turning is not None and ban_on()
                    else ())
        self.ban_releases += len(ban_free)
        new, cells, denied = step_h(states, dists, self.edge_cost, self.wait_cost, free, prio,
                                    self.turn_cost, extra, bias,
                                    self.sec_map, cfg.section_limit, sec_free, forbid, forbid_axle, soft_hold,
                                    turning, ban_free)
        self.section_blocks += len(denied)      # 정원에 막힌 (로봇 × 틱). 0 이면 제한이 논 것
        self.section_releases += len(sec_free)
        if cfg.check:
            self._check_heading_step(t, states, new, cells)
        snap = {}
        for rid in rids:
            snap[rid] = self._apply_heading_move(robots[rid], states[rid], new[rid], dists[rid])
        self._trace.append((t, snap))
        if len(self._trace) > cfg.trace_len:
            del self._trace[0]
        if cfg.export:
            self._log_export_h(t, snap)
        self._update_stagnation_h(new)

    def _stamp_goal_changes(self, t):
        """목표가 바뀐 로봇의 goal_t 갱신 — 우선순위: 계급 → 현재 목표를 받은 뒤 경과 틱(단조 증가, 원 PIBT 방식) → id.
        정체 카운터(stag)를 쓰면 밀린 쪽이 다음 틱 우선권을 얻어 정면 핑퐁 진동 (실측)."""
        for rid in self.rids:
            rb = self.robots[rid]
            if rb["goal"] != rb["goal_prev"]:
                rb["goal_prev"], rb["goal_t"] = rb["goal"], t

    def _update_dock_leave(self):
        """장치 ⑤: 도킹 칸을 떠나는 로봇은 계급 0 (서비스 중과 동급) — 스테이션 칸 위에서 다른 목표를 받은 순간부터
        그 칸에서 체비쇼프 거리 ≥ dock_clear(로봇 길이) 벗어날 때까지 유지(sticky). 근거: 헤딩 설계 §7, 고부하 판정 §3."""
        dc_ = self.cfg.dock_clear
        for rid in self.rids:
            rb = self.robots[rid]
            lf = rb["leave_from"]
            if lf is not None and (rb["state"] not in NAV or rb["pos"] == rb["goal"]
                                   or max(abs(rb["pos"][0] - lf[0]), abs(rb["pos"][1] - lf[1])) >= dc_):
                rb["leave_from"] = lf = None
            if lf is None and rb["state"] in NAV and rb["pos"] in self.station_cells and rb["pos"] != rb["goal"]:
                rb["leave_from"] = rb["pos"]

    @staticmethod
    def _front_path(state, n=3):
        r, c, h = state
        dr, dc = DIRS[h]
        return [(r + i * dr, c + i * dc) for i in range(1, n + 1)]

    def _planned_cells(self, state, dist, n=3):
        """정적 거리장의 최저비용 액션을 따라 다음 이동 칸 n개를 뽑는다(대기는 제외)."""
        out, cur = [], state
        for _ in range(n * 4):
            choices = [st for st, _, _ in candidates_h(cur, dist, self.edge_cost, self.wait_cost,
                                                      self.free, self.turn_cost, bias=1.0) if st != cur]
            if not choices:
                break
            nxt = choices[0]
            if nxt[:2] != cur[:2]:
                out.append(nxt[:2])
                if len(out) == n:
                    break
            cur = nxt
        return out

    def _clear_yield(self, rid):
        rb = self.robots[rid]
        rb["yield_peer"], rb["yield_target"], rb["yield_until"], rb["yield_hold"] = None, None, -1, False
        rb["waitc"] = 0
        self._stag.update(rid, rb["goal"], self.dmap_h(rb["goal"])[rb["pos"][0], rb["pos"][1], rb["h"]])

    def _refresh_yields(self, t, states):
        for rid in self.rids:
            rb = self.robots[rid]
            peer = rb["yield_peer"]
            if peer is None:
                continue
            peer_rb = self.robots[peer]
            peer_goal = peer_rb["yield_target"] if peer_rb["yield_peer"] is not None else peer_rb["goal"]
            danger = set(occupied(states[peer])) | set(
                self._planned_cells(states[peer], self.dmap_h(peer_goal)))
            if t >= rb["yield_until"] or rb["pos"] not in danger:
                self._clear_yield(rid)

    def _escape_cell_ok(self, target, forbidden, occupied_now):
        """대피 칸 조건: 맵 안 통행 가능, 상대 차체·경로 밖, 지금 비어 있고, 어느 방향으로든 차체가 들어간다."""
        if target in forbidden or target in occupied_now:
            return False
        if not (0 <= target[0] < self.H and 0 <= target[1] < self.W and self.free[target]):
            return False
        return any(valid_state(self.free, (target[0], target[1], hh)) for hh in range(4))

    def _side_targets(self, s, forbidden, occupied_now):
        """옆 칸 후보 [(반대 차선 여부, 좌우 순서, 칸)]. 4틱 안에 닿는 칸만. min() 이 반대 차선 아닌 쪽·왼쪽을 먼저 고른다."""
        r, c, h = s
        sides = []
        for order, d in enumerate(((h - 1) % 4, (h + 1) % 4)):
            dr, dc = DIRS[d]
            target = (r + dr, c + dc)
            if not self._escape_cell_ok(target, forbidden, occupied_now):
                continue
            escape = float(self.dmap_h(target)[s])
            if escape < 0 or escape > 4:
                continue
            lane = int(self.lane_dir[target]) if self.lane_dir is not None else -1
            sides.append((lane >= 0 and lane != h, order, target))
        return sides

    def _yield_target(self, loser, winner, states, winner_path):
        """(대피 칸, 제자리 여부). 옆 칸 먼저(반대 차선 아닌 쪽 우선) → 뒤 한 칸 → 제자리 정지(계급 0 으로 상대가 재계획).
        양보 v2(-203, exact,front 전용: 뒤로 물러나 옆으로 빠지는 대피 목표·stag 판정·탈출 가능 쪽 양보)는 -79 대치 상태기계로
        대체돼 2026-09-15 삭제 — 이력은 이동계층_PIBT.md 대치 절."""
        s, other = states[loser], states[winner]
        forbidden = set(occupied(other)) | set(winner_path)
        occupied_now = {cell for rid, state in states.items() if rid != loser for cell in occupied(state)}
        sides = self._side_targets(s, forbidden, occupied_now)
        if sides:
            return min(sides)[2], False
        r, c, h = s
        back = (r - DIRS[h][0], c - DIRS[h][1])
        if self._escape_cell_ok(back, forbidden, occupied_now):
            return back, False
        return self.robots[loser]["pos"], True

    def _headon_peer(self, rid, states, body_owner):
        """rid 바로 앞 칸에 반대 방향으로 선 이동 중 로봇 id. yield_after 틱 이상 실제로 막힌 경우만, 없으면 None."""
        rb, s = self.robots[rid], states[rid]
        if rb["state"] not in NAV or rb["busy"] or rb["yield_peer"] is not None:
            return None
        peer = body_owner.get(self._front_path(s, 1)[0])
        if peer is None or peer == rid:
            return None
        other = self.robots[peer]
        if other["state"] not in NAV or other["busy"] or states[peer][2] != (s[2] + 2) % 4:
            return None
        if max(rb["waitc"], other["waitc"]) < self.cfg.yield_after:    # PIBT 가 스스로 푸는 일회성 마주침은 제외
            return None
        return peer

    def _start_yield(self, t, loser, winner, states, winner_path):
        target, hold = self._yield_target(loser, winner, states, winner_path)
        yb = self.robots[loser]
        yb["yield_peer"], yb["yield_target"] = winner, target
        yb["yield_until"], yb["yield_hold"] = t + self.cfg.yield_ticks, hold
        self.yield_events.append(dict(t=t, yielder=loser, peer=winner,
                                      action="hold" if hold else "sidestep", target=target))

    def _detect_headons(self, t, states, priority, dists):
        """정면 한 칸 조우(서로의 계획 경로가 상대 칸을 지남)를 찾아 낮은 우선순위 로봇에 임시 회피 목표를 건다. 걸었으면 True."""
        order = {rid: i for i, rid in enumerate(priority)}
        body_owner = {cell: rid for rid, state in states.items() for cell in occupied(state)}
        seen, changed = set(), False
        for rid in priority:
            peer = self._headon_peer(rid, states, body_owner)
            if peer is None or frozenset((rid, peer)) in seen:
                continue
            peer_path = self._planned_cells(states[peer], dists[peer])
            own_path = self._planned_cells(states[rid], dists[rid])
            if self.robots[rid]["pos"] not in peer_path or self.robots[peer]["pos"] not in own_path:
                continue          # 서로의 경로가 상대 칸을 지나는 정면만
            seen.add(frozenset((rid, peer)))
            winner, loser = (rid, peer) if order[rid] < order[peer] else (peer, rid)
            if self.robots[loser]["yield_peer"] is not None:
                continue
            self._start_yield(t, loser, winner, states, own_path if winner == rid else peer_path)
            changed = True
        return changed

    # ------------------------------------------------------------
    # 대치(standoff) 상태기계 V2 (-79 B4) — exact,front 전용.
    # V1 설계 docs/2026-09-14_S15P21A106-79_B4_정면대치해소_계획.md §3.3, V2 진단·규칙 R1~R6
    # docs/2026-09-15_S15P21A106-79_B4_V2_대치해소_진단과_규칙.md (로컬). 정리본은 이동계층_PIBT.md 대치 절.
    # ------------------------------------------------------------
    def _wish_cells(self, rid, states, dists):
        """이번 틱 최선 후보(대기 제외)가 필요로 하는 칸 = 로봇이 원하는 자리. (hard 칸, soft(축) 칸) 두 집합."""
        s = states[rid]
        for st, cells, soft in candidates_h(s, dists[rid], self.edge_cost, self.wait_cost, self.free, self.turn_cost):
            if st != s:
                return set(cells), set(soft)
        return set(), set()

    def _constraints_from(self, w, states, dists):
        """w 가 상대에 지우는 (금지 칸, 축 금지 칸): 몸(회전 중이면 스윙 포함) ∪ 원하는 hard 칸 / 원하는 soft 칸 ∪ 회전 중 soft 칸(R2)."""
        wb = self.robots[w]
        hard, soft = self._wish_cells(w, states, dists)
        busy = wb["busy"] > 0
        forbid = set(occupied(states[w])) | hard | (set(wb["swing"]) if busy else set())
        forbid_axle = soft | (set(wb["swing_soft"]) if busy else set())
        return frozenset(forbid), frozenset(forbid_axle)

    def _can_move(self, rid, other, states, dists, body_now, axle_now):
        """rid 가 other 의 제약 아래 **대기 아닌** 합법 후보를 갖는가 (R3). 제3 로봇의 몸·스윙·축은 지금 자리 기준으로 막힌 것으로."""
        forbid, forbid_axle = self._constraints_from(other, states, dists)
        s = states[rid]
        for st, cells, soft in candidates_h(s, dists[rid], self.edge_cost, self.wait_cost, self.free, self.turn_cost):
            if st == s or (cells & forbid) or st[:2] in forbid_axle:
                continue
            if any(body_now.get(c, rid) != rid for c in cells) or any(axle_now.get(c, rid) != rid for c in soft):
                continue
            return True
        return False

    def _judge_dists(self, a, b, states):
        """역할 판정용 거리장: 회전·서비스 중이면 stay, 아니면 기본 — 재계획 거리장은 주변을 막아 후진 후보를 지우므로 쓰지 않는다."""
        out = {}
        for rid in (a, b):
            rb = self.robots[rid]
            out[rid] = stay_map_h(self.free, states[rid]) if rb["state"] in HOLD or rb["busy"] > 0 else self.dmap_h(rb["goal"])
        return out

    def _judge(self, a, b, order, states, body_now, axle_now):
        """(이기는 쪽, 지는 쪽). R3 **움직일 수 있는 쪽이 진다** — 상대 제약 아래 한쪽만 움직일 수 있으면 그쪽이 물러난다(L).
        둘 다/둘 다 아니면 우선순위(V1). exp16 실측: 벽 앞 로봇(후진만 가능, 그 칸이 상대 스윙 wish)이 L 이 되면 후보 0 으로 굳는다."""
        jd = self._judge_dists(a, b, states)
        ma = self._can_move(a, b, states, jd, body_now, axle_now)
        mb = self._can_move(b, a, states, jd, body_now, axle_now)
        if ma != mb:
            return (b, a) if ma else (a, b)
        return (a, b) if order[a] < order[b] else (b, a)

    @staticmethod
    def _owners(states, extra):
        """(몸+스윙 칸 → 로봇, 축 칸 → 로봇)."""
        body_now = {cell: rid for rid, s in states.items() for cell in occupied(s)}
        for rid, cells in extra.items():
            for cell in cells:
                body_now[cell] = rid
        return body_now, {s[:2]: rid for rid, s in states.items()}

    def _detect_standoffs(self, t, states, priority, dists, extra, soft_hold=None):
        """같은 자리를 다투며 둘 다 hd_after 틱 이상 무진전인 두 로봇 → 대치. 걸었으면 True.
        정면(코 맞댐)뿐 아니라 같은 방향(앞차 후진·뒤차 전진)·회전을 막는 옆 축까지 같은 매듭으로 본다 (시드 7·101 실측).
        상대는 회전 중(busy)이어도 된다 (R2 — 시드 42: 두 대가 5틱 회전을 번갈아 해 둘 다 non-busy 인 틱이 없었다).
        R2′ (-159): 임시 예약(회전 중 스윙 extra·soft_hold)에만 막힌 wish 도 상대를 찾는다 — 단 stag ≥ 2×hd_after 부터.
        처음엔 R1 인내가 기다리게 하고(임시 예약은 ≤ turn_ticks 뒤 풀린다), 상대가 회전을 되풀이해 오래 막혀 있으면 같은 매듭
        (load_eval L1·16대·103 매듭 (A): r4 전진 wish 가 r5 스윙에 3,400틱 막힘, 대치 쌍 0)."""
        order = {rid: i for i, rid in enumerate(priority)}
        body_now, axle_now = self._owners(states, extra)
        body_perm = {cell: rid for rid, s in states.items() for cell in occupied(s)}     # 몸만 (영구)
        soft_hold = soft_hold or {}
        changed = False
        for rid in priority:
            if not self._standoff_free(rid):
                continue
            hard, soft = self._wish_cells(rid, states, dists)
            # 영구 예약(몸·축)에 막힌 상대는 hd_after 부터, 임시 예약(스윙·회전 중 soft)에만 막힌 상대는 2×hd_after 부터 (R2′).
            # 회전 한 번은 ≤ turn_ticks 뒤 풀리므로 그 안은 R1 인내에 맡기고, 되풀이 막힘(매듭 (A): 3,400틱)만 대치로 —
            # 문턱을 같이 두면 soft 4칸 고밀도에서 대치가 3배로 늘어 처리량 −10~−29 %(load_eval 28대, 2026-09-15 실측).
            peers = {body_perm[c] for c in hard if c in body_perm} | {axle_now[c] for c in soft if c in axle_now}
            if self._stag.get(rid) >= 2 * self.cfg.hd_after:
                peers |= {body_now[c] for c in hard if c in body_now} | {soft_hold[c] for c in soft if c in soft_hold}
            peers.discard(rid)
            for peer in sorted(peers, key=order.get):
                if self._standoff_free(peer, allow_busy=True):
                    winner, loser = self._judge(rid, peer, order, states, body_now, axle_now)
                    self._start_standoff(t, winner, loser)
                    changed = True
                    break
        return changed

    def _standoff_free(self, rid, allow_busy=False):
        rb = self.robots[rid]
        return (rb["hd_peer"] is None and rb["state"] in NAV and (allow_busy or not rb["busy"])
                and self._stag.get(rid) >= self.cfg.hd_after)

    def _start_standoff(self, t, winner, loser, action="standoff"):
        """action: standoff(새 대치) / swap(상한 교대) / rejudge(R5 즉시 교대). 교대 두 종류는 standoff_swaps 로 함께 센다."""
        swapped = action != "standoff"
        for rid, role, peer in ((winner, "W", loser), (loser, "L", winner)):
            rb = self.robots[rid]
            rb["hd_peer"], rb["hd_role"], rb["hd_until"], rb["hd_swapped"] = peer, role, t + self.cfg.hd_timeout, swapped
            rb["hd_t0"] = t
        if swapped:
            self.standoff_swaps += 1
        else:
            self.standoffs += 1
        self.yield_events.append(dict(t=t, yielder=loser, peer=winner, action=action, target=None))

    def _clear_standoff(self, rid):
        peer = self.robots[rid]["hd_peer"]
        for r in (rid, peer):
            if r is not None:
                rb = self.robots[r]
                rb["hd_peer"], rb["hd_role"], rb["hd_until"], rb["hd_swapped"], rb["hd_t0"] = None, None, -1, False, -1

    def _refresh_standoffs(self, t, states, extra):
        """해제: 한쪽이 서비스·충전에 들어갔거나 두 몸이 더 이상 인접하지 않음(체비쇼프 > 1).
        R5: 교대 전이면 매 틱 재판정 — 지는 쪽이 못 움직이고 이기는 쪽은 움직일 수 있으면 즉시 교대(1회).
        상한(hd_timeout): 미교대면 교대, 교대했으면 해제(다음 감지가 새로 판정)."""
        body_now = axle_now = None
        seen = set()
        for rid in self.rids:
            rb = self.robots[rid]
            peer = rb["hd_peer"]
            if peer is None or rid in seen:
                continue
            seen.add(peer)
            pb = self.robots[peer]
            ended = rb["state"] not in NAV or pb["state"] not in NAV
            if not ended:
                ca, cb = occupied(states[rid]), occupied(states[peer])
                ended = not any(max(abs(x[0] - y[0]), abs(x[1] - y[1])) <= 1 for x in ca for y in cb)
            if ended:
                self._clear_standoff(rid)
                continue
            w, l = (rid, peer) if rb["hd_role"] == "W" else (peer, rid)
            if t >= rb["hd_until"]:
                if rb["hd_swapped"]:
                    self._clear_standoff(rid)
                else:
                    self._start_standoff(t, l, w, action="swap")
            elif not rb["hd_swapped"] and t - rb["hd_t0"] >= self.cfg.hd_after:
                # 시작 뒤 hd_after 틱은 지는 쪽에 시간을 준다 — 판정 직후 한 수(회전) 두고 막힌 것을 "못 움직임"으로 읽어
                # 매 틱 뒤집으면 8틱 주기 교대 churn (시드 42 실측: 한 쌍이 278건)
                if body_now is None:
                    body_now, axle_now = self._owners(states, extra)
                jd = self._judge_dists(w, l, states)
                if not self._can_move(l, w, states, jd, body_now, axle_now) and \
                        self._can_move(w, l, states, jd, body_now, axle_now):
                    self._start_standoff(t, l, w, action="rejudge")

    def _standoff_forbid(self, states, dists):
        """(금지 칸, 축 금지 칸) — 지는 쪽: 이기는 쪽의 몸(회전 중이면 스윙 포함) ∪ 원하는 hard 칸은 못 밟고,
        이기는 쪽이 원하는 soft 칸(회전 앞·대각)·회전 중 soft 칸에는 축을 두지 못한다(제자리 대기도 금지 → 물러나야 한다)."""
        forbid, forbid_axle = {}, {}
        for rid in self.rids:
            rb = self.robots[rid]
            if rb["hd_role"] == "L":
                forbid[rid], forbid_axle[rid] = self._constraints_from(rb["hd_peer"], states, dists)
        return forbid, forbid_axle

    def _goal_held(self):
        """서비스·충전 중인(HOLD) 로봇 몸에 막힌 로봇 집합 → 이번 틱 대기 상승 0 (-281). 막힘 = 목표 칸이 그 몸이거나, 평소 거리장의
        최선 수(대기 제외)가 그 몸 칸을 지나야 한다. HOLD 로봇은 서비스가 끝날 때까지 안 움직이므로 물러나도 길이 안 열린다.
        상승이 붙으면 약 4초 뒤 후진(3 + d+1)이 대기보다 싸져 한 칸 물러났다 돌아오기를 되풀이했다(est_20 12대 6h: 포장대 앞 한 대가
        71초에 30번). 목표가 아닌 로봇도 같다 — 하역 중인 로봇의 몸이 포장대 앞 줄(41행)까지 걸쳐 옆을 지나가던 로봇이 막혔다
        (쓸모없는 후진의 54 %). 우회는 그대로 된다 — 정체 재계획은 상승과 따로 돈다."""
        held = {}
        for o, ob in self.robots.items():
            if ob["state"] in HOLD:
                for cell in self._body_cells(ob):
                    held[cell] = o
        if not held:
            return set()
        out = set()
        for rid, rb in self.robots.items():
            if rb["state"] in HOLD:
                continue
            if held.get(rb["goal"], rid) != rid:
                out.add(rid)
                continue
            if rb["h"] is None:
                continue
            s = (rb["pos"][0], rb["pos"][1], rb["h"])
            own = set(self._body_cells(rb))
            for st, cells, _ in candidates_h(s, self.dmap_h(rb["goal"]), self.edge_cost, self.wait_cost, self.free, self.turn_cost):
                if st != s:
                    if any(held.get(c, rid) != rid for c in set(cells) - own):
                        out.add(rid)
                    break
        return out

    def _patient(self, states, dists, extra, soft_hold):
        """R1 인내: 대기 아닌 최선 후보가 **회전 중 로봇의 임시 예약**(hard 스윙 extra·soft_hold)에만 막힌 로봇 집합 → 이번 틱
        대기 상승 0. 임시 예약은 회전이 끝나면(≤ turn_ticks) 풀리므로 헛회전(d'+1.25)보다 대기(d+1)가 낫다 — 시드 42 실측:
        두 대가 서로의 soft_hold 에 전진을 막혀 5틱 회전을 번갈아 하는 위상 잠금. 몸·축(영구)에 막힌 후보는 해당 없음."""
        if not extra:
            return set()
        hold = {cell: rid for rid, cells in extra.items() for cell in cells}
        body = {cell: rid for rid, s in states.items() for cell in occupied(s)}
        axle = {s[:2]: rid for rid, s in states.items()}
        out = set()
        for rid in self.rids:
            rb = self.robots[rid]
            if rb["busy"] or rb["state"] in HOLD or self._stag.get(rid) <= WAIT_ESC_GRACE:
                continue
            s = states[rid]
            for st, cells, soft in candidates_h(s, dists[rid], self.edge_cost, self.wait_cost, self.free, self.turn_cost):
                if st == s:
                    continue
                temp = any(hold.get(c, rid) != rid for c in cells) or soft_hold.get(st[:2], rid) != rid
                perm = any(body.get(c, rid) != rid for c in cells) or any(axle.get(c, rid) != rid for c in soft)
                if temp and not perm:
                    out.add(rid)
                break
        return out

    def _priority_h(self, t):
        robots = self.robots

        def _rank(r):
            rb = robots[r]
            if rb["busy"] or rb["leave_from"] is not None or rb["yield_hold"]:
                return 0
            if rb["hd_role"] == "W":
                return 0        # -79 대치: 이기는 쪽이 먼저 예약한다(고정) — 지는 쪽은 밀려서 물러난다
            return RANK[rb["state"]]
        return sorted(self.rids, key=lambda r: (_rank(r), -(t - robots[r]["goal_t"]), r))

    def _dists_h(self, t, states, extra):
        """이번 틱 거리장: 서비스·회전 중 = stay, 미도달 = (정체 시) 재계획 거리장, 도달 = 기본."""
        dists = {}
        for rid in self.rids:
            rb = self.robots[rid]
            if rb["state"] in HOLD or rb["busy"] > 0:
                dists[rid] = stay_map_h(self.free, states[rid])
            elif rb["yield_peer"] is not None:
                dists[rid] = self.dmap_h(rb["yield_target"])
            elif rb["hd_role"] == "L":
                # -79: 지는 쪽은 **기본** 거리장 — 재계획 거리장은 주변 칸을 -1 로 막아 후진 후보 자체를 없앤다
                # (시드 42 실측: 지는 쪽의 rev 가 후보에 없어 상한까지 대기 → 역할 교대만 반복). 이기는 쪽은 V2 부터 일반
                # 경로(정체 시 재계획) — exp16 실측: 기본 거리장·calm 인 이기는 쪽이 후진 1칸을 안 해 둘 다 굳었다.
                dists[rid] = self.dmap_h(rb["goal"])
            elif rb["pos"] != rb["goal"]:
                base = self.dmap_h(rb["goal"])
                dists[rid] = self._replan.dist_for(rid, t, states, extra, rb["goal"], base, self._stag.get(rid))
                if dists[rid] is not base:
                    rb["replan"] += 1                       # 재계획 거리장 사용 틱
            else:
                dists[rid] = self.dmap_h(rb["goal"])
        return dists

    def _check_heading_step(self, t, states, new, cells):
        rids = self.rids
        for i, a in enumerate(rids):
            for b in rids[i + 1:]:
                assert not (cells[a] & cells[b]), f"t={t} 점유 겹침 {a}&{b}: {cells[a] & cells[b]}"
                assert not (new[a][:2] == states[b][:2] and new[b][:2] == states[a][:2]), f"t={t} 스왑 {a}<->{b}"

    def _rotation_bookkeeping(self, rb, s0, s1, moved):
        """동작 시작·진행 중 부기 → (이번 틱이 회전 틱인가, 이동 진행 틱인가).

        전진·회전이 여러 틱을 쓴다 (-194: 전진 MOVE_TICKS · 회전 TURN_TICKS). 상태 전이는
        첫 틱에 일어나고 나머지는 busy 로 제자리에 묶인다 (_dists_h 가 stay_map_h 를 준다).
        회전 중에는 스윙 칸을, 이동 중에는 몸 2칸(= 새 칸 + 떠난 칸)을 계속 쥐므로
        쓸고 지나간 영역이 그대로 예약된다.
        """
        if not moved and s1[2] != s0[2]:                 # 회전 시작 (첫 틱)
            rb["turns"] += 1
            if rb["state"] not in NAV:
                rb["turns_idle"] += 1
            rb["busy"] = self.cfg.turn_ticks - 1
            rb["busy_move"] = 0
            rb["swing"] = swing_cells(s0[0], s0[1], s0[2], s1[2])
            # -79: 다틱 회전(-194) 동안 soft 칸(축 금지)도 쥔다 — 축 규칙은 회전 시작·끝 시각 모두에 상대 축이 없어야 한다.
            # hard 스윙은 extra 로 이미 쥐지만 soft 는 결정 틱에만 검사돼 2~5틱째 다른 축이 앞 칸에 들어올 수 있었다.
            rb["swing_soft"] = front_cells(s0[0], s0[1], s0[2], s1[2])
            rb["turn_pair"] = (s0, s1)                   # -277: 회전 내내 금지 조합표로 이웃을 막는다 (step_h turning)
            return True, False
        if moved:                                        # 전진·후진 시작 (첫 틱)
            backward = (s1[0] - s0[0], s1[1] - s0[1]) != DIRS[s0[2]]   # -247: 후진은 더 오래 걸린다
            rb["busy"] = (self.cfg.rev_ticks if backward else self.cfg.move_ticks) - 1
            rb["busy_move"] = 1
            rb["swing"] = set()
            rb["turn_pair"] = None
            return False, False
        if rb["busy"] > 0:                               # 진행 중
            rb["busy"] -= 1
            was_move = bool(rb["busy_move"])
            if rb["busy"] == 0:
                rb["swing"] = set()
                rb["swing_soft"] = set()
                rb["turn_pair"] = None
                rb["busy_move"] = 0
            return (not was_move), was_move
        return False, False

    def _count_nav_h(self, rb, s0, s1, moved, rotating, driving, gd):
        """임무 주행 로봇 카운터: 방문·주행/후진·방향별 흐름·밀림 / 회전 / 대기.

        driving = 이동 진행 틱(칸은 이미 옮겼고 남은 틱을 쓰는 중). 주행 시간이지만
        칸을 새로 밟지는 않으므로 drive 에만 넣고 visit·dir_flow 는 건드리지 않는다 —
        안 그러면 한 번 지나간 칸이 MOVE_TICKS 배로 세어져 히트맵이 뻥튀기된다.
        """
        p0, p1 = s0[:2], s1[:2]
        if driving:
            rb["drive"] += 1          # 주행 '시간' 은 늘고 밟은 '칸' 은 안 는다 (-194)
            rb["waitc"] = 0
            return
        self.visit_count[p1] += 1
        if moved:
            rb["drive"] += 1
            rb["cells"] += 1
            rb["waitc"] = 0
            backward = (p1[0] - p0[0], p1[1] - p0[1]) != DIRS[s0[2]]
            if backward:
                rb["rev"] += 1
            self.dir_flow[p0[0], p0[1], (s0[2] + 2) % 4 if backward else s0[2]] += 1
            if gd[s1] > gd[s0]:
                rb["pushed"] += 1
        elif rotating:
            rb["rot"] += 1
            rb["waitc"] = 0
        else:
            rb["wait"] += 1
            if rb["yield_peer"] is None:
                rb["waitc"] += 1
            self.wait_count[p0] += 1

    def _apply_heading_move(self, rb, s0, s1, gd):
        """로봇 1대 상태 반영 (s0 → s1). 반환: STALL 진단용 snap (s0, busy, 액션, 상태) — busy 는 갱신 전 값."""
        p0, p1 = s0[:2], s1[:2]
        moved = p1 != p0
        snap = (s0, rb["busy"], "fwd" if moved and (p1[0] - p0[0], p1[1] - p0[1]) == DIRS[s0[2]]
                else "rev" if moved else "turn" if s1[2] != s0[2]
                else "busy" if rb["busy"] else "wait", rb["state"])
        rotating, driving = self._rotation_bookkeeping(rb, s0, s1, moved)
        if rb["state"] in NAV:
            self._count_nav_h(rb, s0, s1, moved, rotating, driving, gd)
        elif rb["state"] in SERVICE:
            rb["svc"] += 1
        rb["pos"], rb["h"], rb["heading"] = p1, s1[2], s1[2]
        return snap

    def _log_export_h(self, t, snap):
        """snap 액션: fwd/rev/turn/busy/wait → 리플레이 actions 어휘 (fwd 는 이동이라 actions 에 안 실림)."""
        act = {"fwd": "move", "rev": "reverse", "turn": "rotate", "busy": "rotate", "wait": "wait"}
        for rid in self.rids:
            rb = self.robots[rid]
            a = "service" if rb["state"] in SERVICE else "charge" if rb["state"] == CHARGING else act[snap[rid][2]]
            self.export_log[rid].append((t + 1, rb["pos"][0], rb["pos"][1], rb["h"], a))

    def _update_stagnation_h(self, new):
        for rid in self.rids:
            rb = self.robots[rid]
            if rb["yield_peer"] is not None:
                continue
            if rb["state"] in HOLD:
                self._stag.update(rid, rb["goal"], 0.0)
            else:
                self._stag.update(rid, rb["goal"], self.dmap_h(rb["goal"])[new[rid]])

    # ------------------------------------------------------------
    # 이동 — 칸 모델
    # ------------------------------------------------------------
    def _tick_cell(self, t):
        robots, rids, cfg = self.robots, self.rids, self.cfg
        prio = sorted(rids, key=lambda r: (RANK[robots[r]["state"]], -robots[r]["waitc"], r))
        positions = {rid: robots[rid]["pos"] for rid in rids}
        dists = {}
        for rid in rids:
            rb = robots[rid]
            dists[rid] = self.staymap(rb["pos"]) if rb["state"] in HOLD else self.dmap(rb["goal"])
        new_pos = step(positions, dists, self.edge_cost, self.wait_cost, self.free, prio)
        if cfg.check:
            self._check_cell_step(t, positions, new_pos)
        for rid in rids:
            self._apply_cell_move(rid, t, new_pos[rid], dists[rid])

    def _check_cell_step(self, t, positions, new_pos):
        rids = self.rids
        cells = list(new_pos.values())
        assert len(cells) == len(set(cells)), f"t={t} vertex 충돌"
        for i, a in enumerate(rids):
            for b in rids[i + 1:]:
                assert not (new_pos[a] == positions[b] and new_pos[b] == positions[a]), f"t={t} 스왑 {a}<->{b}"

    def _count_nav_cell(self, rb, p0, p1, moved, gd):
        """임무 주행 로봇 카운터 (칸 모델): v1과 동일 — 임무 주행(경로 내 대기 포함)만 집계."""
        self.visit_count[p1] += 1
        if moved:
            rb["drive"] += 1
            rb["cells"] += 1
            rb["waitc"] = 0
            if gd[p1] > gd[p0]:
                rb["pushed"] += 1
        else:
            rb["wait"] += 1
            rb["waitc"] += 1
            self.wait_count[p0] += 1

    def _update_cell_heading(self, rb, p0, p1):
        """칸 모델: 이동 방향으로 heading 갱신, 방향이 바뀌면 turns +1, 임무 주행이면 방향별 흐름 집계."""
        d = DIRS.index((p1[0] - p0[0], p1[1] - p0[1]))
        if rb["state"] in NAV:
            self.dir_flow[p0[0], p0[1], d] += 1
        if rb["heading"] is not None and d != rb["heading"]:
            rb["turns"] += 1
        rb["heading"] = d

    def _apply_cell_move(self, rid, t, p1, gd):
        """로봇 1대 상태 반영 (칸 모델): 카운터, 방향·회전 수, 위치, 내보내기 로그."""
        rb = self.robots[rid]
        p0 = rb["pos"]
        moved = p1 != p0
        if rb["state"] in NAV:
            self._count_nav_cell(rb, p0, p1, moved, gd)
        elif rb["state"] in SERVICE:
            rb["svc"] += 1
        if moved:
            self._update_cell_heading(rb, p0, p1)
        rb["pos"] = p1
        if self.cfg.export:
            a = "move" if moved else "service" if rb["state"] in SERVICE else "charge" if rb["state"] == CHARGING else "wait"
            self.export_log[rid].append((t + 1, p1[0], p1[1], rb["heading"], a))
