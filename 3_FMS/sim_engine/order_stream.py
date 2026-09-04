# -*- coding: utf-8 -*-
# ============================================================
# 주문 스트림 — 주문·입고 도착 + 태스크 분해 (02 시뮬 WMS 역할, 커널 밖)
# (설계: docs/2026-09-04_커널_라이브러리화_SimPy하네스_설계.md §5, 흐름 규칙: docs/2026-08-31_sim_v2_틱루프_설계.md §6)
#
# 커널(fms_kernel.FmsKernel)은 태스크(from→to)만 받는다. 주문이 몇 개 라인인지, 어느 통로에서
# 나오는지, v1compat 체인의 다음 태스크가 무엇인지는 전부 여기서 결정한다. rng 는 이 객체만 갖는다.
#
# rng 소비 순서 = sim_v2_tasks.py(리팩터링 전)와 동일 — 패리티(v1compat 2317/186.4 등) 근거:
#   생성자: order_times → (main 이면) inbound_times
#   spawn_order(v1compat): integers(N_AISLE) → integers(2) → integers(2) → integers(5)
#   spawn_order(main):     choice([1,2,3]) → integers(N_AISLE) × k → integers(N_PACK)
#   spawn_inbound:         integers(N_INB_ST) → integers(N_AISLE)
# ============================================================
import numpy as np


class OrderStream:
    """주문·입고 스트림. arrivals(t) 로 이 틱의 새 태스크를, on_completed(task, t) 로 후속 태스크를 낸다."""

    def __init__(self, rng, flow, n_orders, order_gap, st_cell, stations,
                 n_inbound=None, inbound_gap=None, k_line_p=(0.5, 0.3, 0.2)):
        assert flow in ("main", "v1compat"), f"알 수 없는 flow: {flow}"
        self.rng, self.flow, self.st_cell = rng, flow, st_cell
        self.n_orders = n_orders
        self.n_inbound = (n_orders if n_inbound is None else n_inbound) if flow == "main" else 0
        self.k_line_p = list(k_line_p)
        self.n_aisle = len(stations["aisle_buf"])
        self.n_pack = len(stations["packing"])
        self.n_inb_st = len(stations["inbound_buf"])
        # 도착 시각표 (지수분포 간격, 틱). 주문 → 입고 순으로 뽑는다 (rng 순서 고정).
        self.order_times = np.cumsum(rng.exponential(order_gap, n_orders)).astype(int) + 1
        if flow == "main":
            gap_in = order_gap if inbound_gap is None else inbound_gap
            self.inbound_times = np.cumsum(rng.exponential(gap_in, self.n_inbound)).astype(int) + 1
        else:
            self.inbound_times = np.array([], dtype=int)
        self.task_seq = 0
        self.orders = {}             # oid -> dict(created, remaining, completed)
        self.chains = {}             # v1compat: oid -> 남은 체인 정의
        self.outstanding_orders = n_orders
        self.outstanding_inbound = self.n_inbound
        self._oi = self._ii = 0

    @property
    def outstanding(self):
        return self.outstanding_orders + self.outstanding_inbound

    # ---- 태스크 생성 ----
    def make_task(self, kind, frm_name, to_name, t, order_id):
        self.task_seq += 1
        return dict(id=self.task_seq, order=order_id, kind=kind,
                    frm_name=frm_name, to_name=to_name,
                    frm=self.st_cell[frm_name], to=self.st_cell[to_name],
                    created=t, assigned=None, completed=None)

    def _spawn_order(self, oid, t):
        rng = self.rng
        if self.flow == "v1compat":
            # v1 spawn_chain 과 동일한 4 draw 를 도착 틱에 일괄 소비 (설계 §6)
            a = int(rng.integers(self.n_aisle))
            chain = [("supply", f"induction[{int(rng.integers(2))}]", f"aisle_buf[{a}]"),
                     ("retrieve", f"aisle_buf[{a}]", f"consol[{int(rng.integers(2))}]"),
                     ("pack", None, f"packing[{int(rng.integers(5))}]")]
            self.chains[oid] = chain
            knd, frm, to = chain.pop(0)
            out = [self.make_task(knd, frm, to, t, oid)]
            self.orders[oid] = dict(created=t, remaining=3, completed=None)
            return out
        k = int(rng.choice([1, 2, 3], p=self.k_line_p))
        aisles = [int(rng.integers(self.n_aisle)) for _ in range(k)]     # 중복 허용
        p = int(rng.integers(self.n_pack))
        uniq = list(dict.fromkeys(aisles))                                # 같은 통로 라인은 토트 1개로 합침
        out = [self.make_task("out", f"aisle_buf[{a}]", f"packing[{p}]", t, oid) for a in uniq]
        self.orders[oid] = dict(created=t, remaining=len(uniq), completed=None)
        return out

    def _spawn_inbound(self, t):
        frm = f"inbound_buf[{int(self.rng.integers(self.n_inb_st))}]"
        to = f"aisle_buf[{int(self.rng.integers(self.n_aisle))}]"
        return [self.make_task("in", frm, to, t, None)]

    # ---- 셸/하네스가 부르는 API ----
    def arrivals(self, t):
        """이 틱(t)에 도착한 주문·입고를 태스크 목록으로. 동일 틱은 주문(oid순) 먼저, 그다음 입고."""
        out = []
        while self._oi < self.n_orders and self.order_times[self._oi] <= t:
            out += self._spawn_order(self._oi, t)
            self._oi += 1
        while self._ii < len(self.inbound_times) and self.inbound_times[self._ii] <= t:
            out += self._spawn_inbound(t)
            self._ii += 1
        return out

    def on_completed(self, task, t):
        """커널 콜백(하역 서비스 만료 직후, 같은 틱 배차 전). 주문 카운터 갱신, v1compat 체인 다음 태스크 반환."""
        oid = task["order"]
        if oid is None:                              # 입고 태스크
            self.outstanding_inbound -= 1
            return []
        od = self.orders[oid]
        od["remaining"] -= 1
        follow = []
        if self.flow == "v1compat" and self.chains.get(oid):
            knd, frm, to = self.chains[oid].pop(0)
            frm = frm or task["to_name"]             # pack 은 직전 도착지에서 출발
            follow.append(self.make_task(knd, frm, to, t, oid))
        if od["remaining"] == 0:
            od["completed"] = t
            self.outstanding_orders -= 1
        return follow
