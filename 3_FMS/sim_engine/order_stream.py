# -*- coding: utf-8 -*-
# ============================================================
# 주문 스트림 — 주문·입고 도착 + 태스크 분해 (02 시뮬 WMS 역할, 커널 밖)
# (설계·흐름 규칙: docs/커널_시뮬_구조.md#태스크-흐름)
#
# 커널(fms_kernel.FmsKernel)은 태스크(from→to)만 받는다. 주문이 몇 개 라인인지, 어느 통로에서
# 나오는지, v1compat 체인의 다음 태스크가 무엇인지는 전부 여기서 결정한다. rng 는 이 객체만 갖는다.
#
# rng 소비 순서 = sim_v2_tasks.py(리팩터링 전)와 동일 — 패리티(v1compat 2317/186.4 등) 근거:
#   생성자: order_times → (main 이면) inbound_times
#   spawn_order(v1compat): integers(N_AISLE) → integers(2) → integers(2) → integers(5)
#   spawn_order(main):     choice([1,2,3]) → integers(N_AISLE) × k → integers(N_PACK)
#   spawn_inbound:         integers(N_INB_ST) → integers(N_AISLE)
#
# 고정 시간 모드 (horizon 지정, -145 설계 §1): 유한 건수 대신 "T 안에서 생기는 만큼". 교대(shifts)로 T 를 k 등분해
# 각 창에는 그 종류(in=입고 / out=출고)의 도착만 생긴다 — 입고·출고가 시간상 겹치지 않는다. 창 밖에 그 종류의
# 도착은 0 건이고 큐에 미루는 것도 아니다. rng 는 출고 창 전부 → 입고 창 전부 순으로 소비.
# ============================================================
import numpy as np

from kernel.core import MAX_TOTES_PER_TRIP

# 주문 단위 경계 (2026-09-14 결정): 토트 합계가 이 수를 넘는 주문은 팔레트 출고(업자 주문)로 보고 시뮬 밖 — 개인 소비자 대상 창고.
# 그 아래 큰 주문(7~24토트)은 토트마다 태스크 하나라 여러 왕복으로 소화된다. 0 = 제한 없음.
# 참조 데이터 6,000건: 6토트 초과 1 % 가 물량 11 % (한 줄 1,277개 같은 줄이 원인), 24토트 초과는 3~6건·물량 3.5~5 %.
MAX_ORDER_TOTES = 24


def shift_windows(horizon, shifts):
    """교대 토큰열 → [(kind, start, end)] (틱, [start, end)). T 를 len(shifts) 등분하고 연속된 같은 토큰은 한 창으로 합친다.
    기본 ("in","out","out") → [("in", 0, T/3), ("out", T/3, T)]."""
    k = len(shifts)
    assert k >= 1 and all(s in ("in", "out") for s in shifts), f"교대 토큰은 in|out: {shifts}"
    bounds = [round(i * horizon / k) for i in range(k + 1)]
    out = []
    for i, kind in enumerate(shifts):
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1], bounds[i + 1])
        else:
            out.append((kind, bounds[i], bounds[i + 1]))
    return out


# 교대 기본값 — 출고 전용 (계약 v3.16, 2026-09-21). 09-14 「입고는 켜지 않는다」를 입구마다 따로 막던 것을 엔진 한 곳으로.
# 입고를 돌리려면 --shifts=in,out,out 을 명시한다. sim_v2_tasks·fms_core 가 이 이름을 읽는다 — 리터럴 복제 금지(-234·-251 같은 병).
DEFAULT_SHIFTS = ("out",)


class OrderStream:
    """주문·입고 스트림. arrivals(t) 로 이 틱의 새 태스크를, on_completed(task, t) 로 후속 태스크를 낸다."""

    def __init__(self, rng, flow, n_orders, order_gap, st_cell, stations,
                 n_inbound=None, inbound_gap=None, k_line_p=(0.5, 0.3, 0.2),
                 horizon=None, shifts=DEFAULT_SHIFTS, dt=1.0,
                 orders=None, rack_map=None, tote_units=None, max_order_totes=MAX_ORDER_TOTES):
        assert flow in ("main", "v1compat"), f"알 수 없는 flow: {flow}"
        self.rng, self.flow, self.st_cell = rng, flow, st_cell
        self.k_line_p = list(k_line_p)
        self.n_aisle = len(stations["aisle_buf"])
        self.n_pack = len(stations["packing"])
        self.n_inb_st = len(stations["inbound_buf"])
        self.horizon = horizon
        self.explicit_orders = None                  # 명시 주문 모드(-156)면 [(틱, [(버퍼, 왕복수), …])]
        self.orders_skipped = 0
        self.orders_oversize = 0
        self.totes_total = 0
        gap_in = order_gap if inbound_gap is None else inbound_gap
        if orders is not None:
            self._init_explicit(flow, orders, rack_map, tote_units, n_inbound, horizon, shifts, gap_in, dt, max_order_totes)
        elif horizon is None:
            self._init_finite(flow, n_orders, n_inbound, order_gap, gap_in)
        else:
            self._init_horizon(flow, horizon, shifts, order_gap, gap_in)
        self.task_seq = 0
        self.orders = {}             # oid -> dict(created, remaining, completed)
        self.chains = {}             # v1compat: oid -> 남은 체인 정의
        self.outstanding_orders = self.n_orders
        self.outstanding_inbound = self.n_inbound
        self._oi = self._ii = 0

    def _init_finite(self, flow, n_orders, n_inbound, order_gap, gap_in):
        """유한 주문 모드: 주문 n_orders + 입고(main: 기본 = 주문 수) 도착 시각표. 주문 → 입고 순으로 뽑는다 (rng 순서 고정)."""
        rng = self.rng
        self.windows = None
        self.n_orders = n_orders
        if flow != "main":
            self.n_inbound = 0                       # v1compat: 입고 없음
        elif n_inbound is None:
            self.n_inbound = n_orders                # main 기본: 입고 = 주문 수
        else:
            self.n_inbound = n_inbound
        # 도착 시각표 (지수분포 간격, 틱).
        self.order_times = np.cumsum(rng.exponential(order_gap, n_orders)).astype(int) + 1
        if flow == "main":
            self.inbound_times = np.cumsum(rng.exponential(gap_in, self.n_inbound)).astype(int) + 1
        else:
            self.inbound_times = np.array([], dtype=int)

    def _init_explicit(self, flow, orders, rack_map, tote_units, n_inbound, horizon, shifts, gap_in, dt=1.0,
                       max_order_totes=MAX_ORDER_TOTES):
        """명시 주문 모드 (-156, docs/커널_시뮬_구조.md#명시-주문-모드): 큐 명세 §1-1 `outbound[]` 를 그대로 흘린다.
        도착 틱 = ordered_at_s / dt (dt = 틱 길이[초], 기본 1.0 = 1틱 1초; -116). 라인 rack_id → rack_map → 버퍼, 같은 버퍼는 qty 를 합쳐 토트로 묶고
        토트 수 = ceil(qty 합 / tote_units) (없으면 버퍼당 1). 토트는 하나가 태스크 하나라 큰 주문은 여러 왕복으로 소화된다
        (같은 버퍼 토트는 capacity 만큼 동승, 커널 dispatch). 합계가 max_order_totes(기본 24)를 넘는 주문만 팔레트 흐름으로 제외하고
        orders_oversize 에 센다 (2026-09-14; v2.6~v3.4 는 6토트 초과 제외).
        출고 교대 창은 쓰지 않는다(파일 시각이 진실).
        horizon 밖(t ≥ T) 주문은 버리고 orders_skipped 에 센다. 입고는 기존 규칙(간격·in 창) 그대로."""
        assert flow == "main", "명시 주문 모드는 main 흐름만"
        assert rack_map, "명시 주문 모드는 rack_map(map/rack_buffers.json) 필요"
        assert tote_units is None or tote_units >= 1, f"tote_units 는 1 이상 (상품 개수): {tote_units}"
        parsed = [_parse_order(od, rack_map, tote_units, dt) for od in orders]
        parsed = self._filter_orders(parsed, horizon, max_order_totes)
        parsed.sort(key=lambda p: p[0])                              # 안정 정렬: 같은 틱은 파일 순서
        self.explicit_orders = parsed
        self.n_orders = len(parsed)
        self.order_times = np.array([p[0] for p in parsed], dtype=int)
        self._init_explicit_inbound(horizon, shifts, gap_in, n_inbound)

    def _filter_orders(self, parsed, horizon, max_order_totes):
        """horizon 밖(t ≥ T) 제외 → orders_skipped. 토트 합계가 max_order_totes 초과 → 팔레트 출고로 시뮬 밖, orders_oversize.
        로봇 한 대 적재(MAX_TOTES_PER_TRIP=6)를 넘는 주문은 토트마다 태스크 하나라 커널이 여러 왕복으로 나른다(-177 은 제외했음).
        개인 소비자 창고에 업자 주문은 없다 (2026-09-14)."""
        if horizon is not None:
            kept = [p for p in parsed if p[0] < horizon]
            self.orders_skipped = len(parsed) - len(kept)
            parsed = kept
        if max_order_totes:
            self.orders_oversize = sum(_order_totes(p) > max_order_totes for p in parsed)
            parsed = [p for p in parsed if _order_totes(p) <= max_order_totes]
        return parsed

    def _init_explicit_inbound(self, horizon, shifts, gap_in, n_inbound):
        """입고: 고정 시간이면 in 창에서 간격 생성, 유한이면 주문 수만큼(기본) 간격 생성 — 간격 모드와 같은 식."""
        if horizon is not None:
            self.windows = shift_windows(horizon, tuple(shifts))
            self.inbound_times = np.concatenate([self._window_times(s, e, gap_in)
                                                 for kind, s, e in self.windows if kind == "in"] or [np.array([], dtype=int)])
        else:
            self.windows = None
            n_in = self.n_orders if n_inbound is None else n_inbound
            self.inbound_times = np.cumsum(self.rng.exponential(gap_in, n_in)).astype(int) + 1
        self.n_inbound = len(self.inbound_times)

    def _init_horizon(self, flow, horizon, shifts, order_gap, gap_in):
        """고정 시간·교대 모드: 창마다 그 종류(out/in)의 도착만. 주문 창 → 입고 창 순으로 뽑는다."""
        assert flow == "main", "고정 시간 모드는 main 흐름만 (v1compat 은 패리티 전용)"
        self.windows = shift_windows(horizon, tuple(shifts))
        self.order_times = np.concatenate([self._window_times(s, e, order_gap)
                                           for kind, s, e in self.windows if kind == "out"] or [np.array([], dtype=int)])
        self.inbound_times = np.concatenate([self._window_times(s, e, gap_in)
                                             for kind, s, e in self.windows if kind == "in"] or [np.array([], dtype=int)])
        self.n_orders, self.n_inbound = len(self.order_times), len(self.inbound_times)

    def _window_times(self, start, end, gap):
        """창 [start, end) 안의 도착 틱: 창 시작부터 지수 간격 누적, 유한 모드와 같은 규칙(floor + 1)으로 틱화, 창 끝에서 절단.
        한 번에 하나씩 뽑는다(창 길이를 넘는 마지막 draw 도 소비됨 — 시드 고정이면 결정론)."""
        out, acc = [], 0.0
        while True:
            acc += float(self.rng.exponential(gap))
            tk = start + int(acc) + 1
            if tk >= end:
                return np.array(out, dtype=int)
            out.append(tk)

    @property
    def outstanding(self):
        return self.outstanding_orders + self.outstanding_inbound

    def arrival_ticks(self):
        """도착이 있는 틱의 오름차순 목록 (주문·입고 합집합) — SimPy 도착 프로세스가 이 시각마다 arrivals(t) 를 부른다."""
        return sorted(set(self.order_times.tolist()) | set(self.inbound_times.tolist()))

    def window_of(self, t):
        """고정 시간 모드: 틱 t 가 속한 교대 종류 ('in'|'out'). 유한 모드는 None."""
        if self.windows is None:
            return None
        for kind, s, e in self.windows:
            if s <= t < e:
                return kind
        return None

    # ---- 태스크 생성 ----
    def make_task(self, kind, frm_name, to_name, t, order_id):
        self.task_seq += 1
        return dict(id=self.task_seq, order=order_id, kind=kind,
                    frm_name=frm_name, to_name=to_name,
                    frm=self.st_cell[frm_name], to=self.st_cell[to_name],
                    created=t, assigned=None, completed=None)

    def _spawn_order(self, oid, t):
        rng = self.rng
        if self.explicit_orders is not None:
            # 포장대는 시뮬(WMS 역할)이 배정 — 간격 모드와 같은 1 draw. 버퍼별 왕복 수만큼 출고 태스크.
            p = int(rng.integers(self.n_pack))
            out = [self.make_task("out", f"aisle_buf[{b}]", f"packing[{p}]", t, oid)
                   for b, totes in self.explicit_orders[oid][1] for _ in range(totes)]
            self.orders[oid] = dict(created=t, remaining=len(out), completed=None)
            self.totes_total += len(out)
            return out
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
        self.totes_total += len(out)
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


def _parse_order(od, rack_map, tote_units, dt):
    """큐 명세 §1-1 주문 하나 → (도착 틱, [(버퍼, 토트 수)]). 같은 버퍼는 qty 합쳐 ceil(합 / tote_units), tote_units 없으면 버퍼당 1."""
    assert od["ordered_at_s"] >= 0, f"ordered_at_s 는 0 이상: {od}"
    groups = {}
    for ln in od["lines"]:
        rid = ln["rack_id"]
        if rid not in rack_map:
            raise KeyError(f"rack_id {rid!r} 가 rack_buffers.json 에 없음 (order {od.get('order_id')})")
        groups[rack_map[rid]] = groups.get(rack_map[rid], 0) + int(ln.get("qty", 1))
    totes = [(b, -(-q // tote_units) if tote_units else 1) for b, q in sorted(groups.items())]
    return int(od["ordered_at_s"] / dt), totes


def _order_totes(parsed_order):
    """(틱, [(버퍼, n)]) 의 토트 합계."""
    return sum(n for _, n in parsed_order[1])
