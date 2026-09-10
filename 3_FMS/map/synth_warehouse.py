# -*- coding: utf-8 -*-
# ============================================================
# 합성 창고 생성기 — 파라메트릭 레이아웃 + 토폴로지 동시 출력 (S15P21A106-139)
#
# 왜 "동시 출력"인가. from_theta.extract_topology 는 wallA 좌표 상수에 묶여 있고, 규칙 기반
# 자동 추출은 이 맵에서 깨졌다 (통로 50개·순환로 0개 — ai_theta/data/README.md '설계 결정').
# 그런데 **생성기는 추출할 필요가 없다** — 통로를 어디에 팠는지 자기가 안다. 그래서 맵 세트에
# topology.json 을 같이 써 넣고, from_theta·map_loader 가 그걸 읽는다 (sim_engine/topology_spec.py).
# 토폴로지 추출 일반화(B트랙 ⑪)를 기다리지 않고 합성 창고 데이터셋(로드맵 3단계)에 들어갈 수 있다.
#
# 창고 모형 — wallA 실측에서 뽑았다 (2026-09-08, docs/합성_창고_생성기.md §1):
#
#     ┌──────────── 북 밴드 (band_n) ────────────┐
#     │서                                      동│   링 = 순환로가 도는 사각 띠
#     │밴 │ │ │ │  랙 블록 = 랙|통로 반복  │ │ │ 밴│   랙 블록 = 세로 통로 n 개 × 랙
#     │드 │ │ │ │  (통로 중심 = pitch 간격) │ │ │ 드│   통로 양 끝 = 교차로(목) + aisle_buf
#     └──────────── 남 밴드 (band_s) ────────────┘
#
# 링 밖은 전부 벽이다. wallA 의 북쪽 부속 구역(r74~88, returns·output[1])은 모형에 없다 —
# 그 3칸은 북 밴드 선으로 옮겨 잡는다 (docs §3 '재현하지 않는 것').
#
# 출력 = map_loader 가 그대로 읽는 맵 세트 한 벌:
#     occupancy_grid.npy  0.1 m 격자 (다운샘플하면 의도한 1 m 통행성이 정확히 나오게 씀)
#     stations.json       스테이션 좌표(m) + charge_zone 키
#     charge_zone.json    충전 존 사각형(m)
#     topology.json       TopologySpec — 통로·밴드·교차로 좌표
#     warehouse_spec.json 이 파일이 받은 파라미터 (재생성용)
#
# 사용:
#     python synth_warehouse.py wallA  ../ai_theta/data/synth/wallA      # 실측 프로파일 재현
#     python synth_warehouse.py random ../ai_theta/data/synth --n 8 --seed 0
#     python synth_warehouse.py check  ../ai_theta/data/synth/wallA      # 공식 맵과 링 영역 대조
# ============================================================
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sim_engine"))
from map_loader import CELL_M, K, OBSTACLE_VALUES, OFFSET_M, OX  # noqa: E402
from topology_spec import TopologySpec  # noqa: E402

RACK_VALUE = 2                 # 생성 격자는 장애물을 전부 '랙'으로 표기 (map_loader.OBSTACLE_VALUES 안)
SPEC_FILE = "warehouse_spec.json"
INDEX_FILE = "README.md"
SIDES = ("S", "N", "W", "E")
MIN_STATION_GAP = 3            # 목표 칸 최소 간격 — 2칸 차체가 겹치지 않는 조건 (fms_kernel 경고)

# 균등 혼잡 대수 환산 — 공식 맵과 같은 기하인 r11p6l21 이 통로차단 ON 에서 free 1619 칸이고,
# θ 탐색 권장 조건의 기준 대수가 20대다 (SIM_RUN_CONTRACT §5). 창고 크기가 달라도 칸당 로봇
# 밀도를 맞춰야 "기하 차이"와 "혼잡도 차이"가 섞이지 않는다 (θ 감도 실험 §0 — θ 는 막힐 때 일한다).
FLEET_CELLS_PER_ROBOT = 81
# θ 가 판정 가능한 대수 구간 (2026-09-04 대수별 결과 §4: 8대는 약하고 28대는 부호가 갈린다)
THETA_FLEET_BAND = (12, 24)
# 인덱스 표의 처리량 열을 재는 조건 — 창고 난이도 비교용 고정 조건이지 권장 조건이 아니다
INDEX_SIM = dict(robots=12, orders=60, order_gap=15, seed=101, aisle_block=1)


# ------------------------------------------------------------
# 1) 스펙
# ------------------------------------------------------------
class StationLine:
    """스테이션 한 종류를 밴드 한 변의 직선 위에 놓는 규칙.

    side  = 밴드 (S 남 / N 북 / W 서 / E 동)
    inset = 그 변의 바깥 모서리에서 안쪽으로 들어간 칸 수
    first/step = 변을 따라가는 좌표(S·N 은 열, W·E 는 행). 생략하면 사용 가능 구간에 균등 배치.
    """

    __slots__ = ("kind", "side", "inset", "count", "first", "step")

    def __init__(self, kind, side, count, inset=0, first=None, step=None):
        assert side in SIDES, f"side 는 {SIDES} 중 하나: {side}"
        assert count >= 1, f"{kind}: count 는 1 이상"
        self.kind, self.side, self.count = kind, side, int(count)
        self.inset, self.first, self.step = int(inset), first, step

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d):
        return cls(d["kind"], d["side"], d["count"], d.get("inset", 0),
                   d.get("first"), d.get("step"))


class WarehouseSpec:
    """창고 하나를 만드는 파라미터 전부. 값은 1 m 격자 칸 단위."""

    __slots__ = ("name", "n_aisles", "aisle_pitch", "aisle_half_width", "aisle_len",
                 "band_s", "band_n", "band_w", "band_e", "origin", "margin",
                 "raw_shape", "extra_blocks", "station_lines",
                 "charge_zone_col_inset", "charge_zone_row_inset", "seed")

    def __init__(self, name, n_aisles=11, aisle_pitch=6, aisle_half_width=1, aisle_len=21,
                 band_s=7, band_n=6, band_w=12, band_e=10, origin=(40, 20), margin=2,
                 raw_shape=None, extra_blocks=(), station_lines=(),
                 charge_zone_col_inset=4, charge_zone_row_inset=1, seed=None):
        self.name = name
        self.n_aisles, self.aisle_pitch = int(n_aisles), int(aisle_pitch)
        self.aisle_half_width, self.aisle_len = int(aisle_half_width), int(aisle_len)
        self.band_s, self.band_n = int(band_s), int(band_n)
        self.band_w, self.band_e = int(band_w), int(band_e)
        self.origin, self.margin = tuple(int(v) for v in origin), int(margin)
        self.raw_shape = None if raw_shape is None else tuple(int(v) for v in raw_shape)
        self.extra_blocks = tuple(tuple(int(v) for v in b) for b in extra_blocks)
        self.station_lines = tuple(station_lines)
        self.charge_zone_col_inset = int(charge_zone_col_inset)
        self.charge_zone_row_inset = int(charge_zone_row_inset)
        self.seed = seed
        self._validate()

    def _validate(self):
        assert self.n_aisles >= 2, "통로는 2개 이상"
        assert self.aisle_half_width >= 1, "통로 반폭은 1 이상 (폭 3 이상)"
        # 통로 폭 + 랙 1열 이상. 이보다 좁으면 이웃 통로가 맞닿거나 겹쳐 랙 블록이 통째로 빈 홀이
        # 된다 — 창고가 아닌 것이 데이터셋에 조용히 섞인다.
        width = 2 * self.aisle_half_width + 1
        assert self.aisle_pitch >= width + 1, \
            f"통로 사이에 랙이 안 남는다 — pitch({self.aisle_pitch}) >= 통로 폭({width}) + 1 필요"
        assert self.aisle_len >= 3, "통로 길이는 3 이상"
        assert min(self.band_s, self.band_n, self.band_w, self.band_e) >= 3, "밴드 두께는 3 이상"
        assert self.origin[0] >= 1 and self.origin[1] >= 1, "링은 격자 0행·0열에 닿으면 안 된다"
        assert self.charge_zone_col_inset + 2 <= self.band_e, "충전 존이 동 밴드를 벗어난다"
        for kind, cnt in self.station_counts().items():
            assert cnt >= 1, f"{kind} 개수는 1 이상"

    # -- 파생 기하 ---------------------------------------------
    @property
    def rack_span(self):
        """랙 블록 열 폭 (통로 바깥쪽 랙까지 포함)."""
        return (self.n_aisles - 1) * self.aisle_pitch + 2 * (self.aisle_pitch // 2) + 1

    def topology(self):
        """이 스펙이 뜻하는 TopologySpec — 레이아웃과 같은 좌표에서 나온다."""
        r0, c0 = self.origin
        va_r0 = r0 + self.band_s
        va_r1 = va_r0 + self.aisle_len
        rack_c0 = c0 + self.band_w
        first = rack_c0 + self.aisle_pitch // 2
        return TopologySpec(
            va_rows=(va_r0, va_r1),
            va_centers=[first + self.aisle_pitch * k for k in range(self.n_aisles)],
            va_half_width=self.aisle_half_width,
            band_s_rows=(r0, va_r0),
            band_n_rows=(va_r1, va_r1 + self.band_n),
            band_w_cols=(c0, rack_c0),
            band_e_cols=(rack_c0 + self.rack_span, rack_c0 + self.rack_span + self.band_e),
            junction_rows=(va_r0 - 1, va_r1),
        )

    def grid_shape(self):
        """1 m coarse 격자 크기 (H, W). raw_shape 이 있으면 그쪽에서 역산."""
        if self.raw_shape is not None:
            h, w = self.raw_shape
            return (-(-h // K), -(-(w + OX) // K))
        topo = self.topology()
        return (topo.ring_rows[1] + self.margin, topo.ring_cols[1] + self.margin)

    def station_counts(self):
        out = {"aisle_buf": 2 * self.n_aisles}
        for line in self.station_lines:
            out[line.kind] = out.get(line.kind, 0) + line.count
        return out

    # -- 직렬화 ------------------------------------------------
    def to_dict(self):
        d = {k: getattr(self, k) for k in self.__slots__}
        d["origin"] = list(self.origin)
        d["raw_shape"] = None if self.raw_shape is None else list(self.raw_shape)
        d["extra_blocks"] = [list(b) for b in self.extra_blocks]
        d["station_lines"] = [ln.to_dict() for ln in self.station_lines]
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["station_lines"] = [StationLine.from_dict(x) for x in d.get("station_lines", ())]
        return cls(**d)


# ------------------------------------------------------------
# 2) 격자
# ------------------------------------------------------------
def build_blocked(spec):
    """1 m 격자 장애물 마스크 — 링 밖은 전부 벽, 랙 블록에서 통로만 뚫고, extra_blocks 를 덮는다."""
    topo = spec.topology()
    H, W = spec.grid_shape()
    rr, cc = topo.ring_rows, topo.ring_cols
    assert rr[1] <= H and cc[1] <= W, f"링 {rr}×{cc} 이 격자 {(H, W)} 를 벗어난다"

    blocked = np.ones((H, W), dtype=bool)
    blocked[rr[0]:rr[1], cc[0]:cc[1]] = False                       # 링 내부 개방
    rack_c0 = topo.band_w_cols[1]
    rack_c1 = topo.band_e_cols[0]
    blocked[topo.va_rows[0]:topo.va_rows[1], rack_c0:rack_c1] = True  # 랙 블록 채우고
    for center in topo.va_centers:                                    # 통로만 다시 뚫는다
        a0, a1 = topo.aisle_cols(center)
        blocked[topo.va_rows[0]:topo.va_rows[1], a0:a1] = False
    for r0, r1, c0, c1 in spec.extra_blocks:                          # 실측 창고의 구조물
        blocked[r0:r1 + 1, c0:c1 + 1] = True
    return blocked, topo


def to_raw(blocked, raw_shape=None):
    """1 m 마스크 → 0.1 m 격자. map_loader.load_map 이 다운샘플하면 정확히 blocked 가 나온다.

    다운샘플은 왼쪽 OX(=4) 칸 패딩 뒤 K×K max pooling 이므로, coarse (r, c) 는 원본
    행 [10r, 10r+10) × 열 [10c-4, 10c+6) 를 덮는다 — 겹치지 않는 완전 분할이다.
    """
    H, W = blocked.shape
    raw_h, raw_w = (K * H, K * W - OX) if raw_shape is None else raw_shape
    raw = np.zeros((raw_h, raw_w), dtype=np.uint8)
    for r, c in np.argwhere(blocked):
        r, c = int(r), int(c)
        raw[K * r:K * r + K, max(0, K * c - OX):K * c + K - OX] = RACK_VALUE
    return raw


def coarse_free(raw):
    """map_loader.load_map 의 다운샘플과 같은 계산 (검산용)."""
    m = np.isin(raw, OBSTACLE_VALUES).astype(np.uint8)
    m = np.pad(m, ((0, 0), (OX, 0)), constant_values=1)
    h, w = m.shape
    m = np.pad(m, ((0, (-h) % K), (0, (-w) % K)), constant_values=1)
    return m.reshape(m.shape[0] // K, K, m.shape[1] // K, K).max(axis=(1, 3)) == 0


# ------------------------------------------------------------
# 3) 스테이션
# ------------------------------------------------------------
def _line_positions(count, first, step, lo, hi):
    """변을 따라가는 좌표 count 개 — 지정 first/step 이 있으면 그대로, 없으면 [lo, hi) 에 균등.

    자동 배치의 간격은 최소 MIN_STATION_GAP(=3) 이다. 2칸 차체가 겹치지 않는 조건이고
    (close_station_pairs), 균등 분배가 그보다 촘촘해지면 간격 3으로 붙여 가운데 정렬한다.
    """
    if first is not None:
        s = step if step is not None else 1
        return [first + s * i for i in range(count)]
    span = hi - lo
    gap = max(MIN_STATION_GAP, span // (count + 1))
    total = gap * (count - 1)
    assert total < span, \
        f"스테이션 {count}개를 길이 {span} 직선에 간격 {MIN_STATION_GAP} 로 못 넣는다 — 개수나 밴드 크기 조정"
    return [lo + (span - total) // 2 + gap * i for i in range(count)]


def place_stations(spec, topo):
    """{종류: [(r, c)]} — 통로 양 끝의 aisle_buf 는 규칙 고정, 나머지는 station_lines 대로.

    first 를 안 준 줄들은 **(변, inset) 이 같으면 한 직선을 나눠 쓴다** — 각자 균등 배치하면
    같은 줄 위에서 겹치기 때문이다. 나눠 쓰는 줄들은 선언 순서대로 슬롯을 받는다.
    """
    # 통로 끝 버퍼: 북쪽은 목(junction) 한 칸 위, 남쪽은 목 그 자리 — wallA 실측(69행·46행) 규칙
    cells = {"aisle_buf": [(topo.va_rows[1] + 1, c) for c in topo.va_centers] +
                          [(topo.va_rows[0] - 1, c) for c in topo.va_centers]}
    rack_c0, rack_c1 = topo.band_w_cols[1], topo.band_e_cols[0]
    shared = {}                      # (side, inset) → 그 직선을 나눠 쓰는 줄들의 총 개수
    for ln in spec.station_lines:
        if ln.first is None:
            shared[(ln.side, ln.inset)] = shared.get((ln.side, ln.inset), 0) + ln.count
    taken = {}                       # (side, inset) → 지금까지 나눠 준 슬롯 수
    for ln in spec.station_lines:
        key = (ln.side, ln.inset)
        along = (rack_c0, rack_c1) if ln.side in ("S", "N") else topo.va_rows
        if ln.first is None:
            slots = _line_positions(shared[key], None, None, *along)
            used = taken.get(key, 0)
            pos = slots[used:used + ln.count]
            taken[key] = used + ln.count
        else:
            pos = _line_positions(ln.count, ln.first, ln.step, *along)
        if ln.side in ("S", "N"):
            row = (topo.band_s_rows[0] + ln.inset if ln.side == "S"
                   else topo.band_n_rows[1] - 1 - ln.inset)
            pts = [(row, c) for c in pos]
        else:
            col = (topo.band_w_cols[0] + ln.inset if ln.side == "W"
                   else topo.band_e_cols[1] - 1 - ln.inset)
            pts = [(r, col) for r in pos]
        cells.setdefault(ln.kind, []).extend(pts)
    return cells


def charge_zone_rect(spec, topo):
    """충전 존 (r0, r1, c0, c1) 포함 구간 — 동 밴드 안쪽, 랙 구간 행."""
    c0 = topo.band_e_cols[0] + spec.charge_zone_col_inset
    c1 = topo.band_e_cols[1] - 1
    r0 = topo.va_rows[0] + spec.charge_zone_row_inset
    r1 = topo.va_rows[1] - 1 - spec.charge_zone_row_inset
    return (r0, r1, c0, c1)


def _check_dockable(cells, blocked):
    """스테이션 자리가 실제로 도킹 가능한지 — map_loader._station_cells 의 스냅 규칙과 같은 순서.

    자리 자체가 막혀 있어도 상하좌우 첫 free 칸으로 붙으므로(v1 규칙) 그것까지 허용한다.
    wallA 의 charge_q[2](56,105)가 기둥에 걸려 55행으로 붙는 것이 실제 그 경우다.
    """
    H, W = blocked.shape
    for kind, pts in cells.items():
        for r, c in pts:
            assert 0 <= r < H and 0 <= c < W, f"{kind} 자리 ({r},{c}) 가 격자 밖"
            near = [(r, c), (r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
            assert any(0 <= rr < H and 0 <= cc < W and not blocked[rr, cc] for rr, cc in near), \
                f"{kind} 자리 ({r},{c}) 와 사방이 전부 장애물 — 배치 규칙/extra_blocks 확인"


def close_station_pairs(cells, min_cheb=3):
    """목표 칸끼리 체비쇼프 거리 < 3 인 쌍 — 2칸 차체가 겹쳐 핑퐁 진동이 난다.

    커널(fms_kernel)이 실행할 때마다 같은 검사를 경고로 낸다. 여기서 미리 세어 두면
    생성 단계에서 배치를 고칠 수 있다. 실패로 보지 않는 이유는 **공식 맵 wallA 도 한 쌍
    걸리기 때문**이다 (charge_q (53,105)-(55,105), 기둥에 걸려 한 칸 밀린 결과).
    """
    pts = [rc for lst in cells.values() for rc in lst]
    return [(a, b) for i, a in enumerate(pts) for b in pts[i + 1:]
            if max(abs(a[0] - b[0]), abs(a[1] - b[1])) < min_cheb]


def cell_to_xy(r, c):
    """격자 칸 → stations.json 좌표(m). map_loader._station_cells 의 역변환."""
    return [round(c + 0.1, 1), round(r + 0.5, 1)]


# ------------------------------------------------------------
# 4) 세트 쓰기
# ------------------------------------------------------------
def build_set(spec):
    """스펙 → (raw 0.1 m 격자, stations dict, charge_zone dict, TopologySpec, blocked)."""
    blocked, topo = build_blocked(spec)
    raw = to_raw(blocked, spec.raw_shape)
    got = coarse_free(raw)
    assert got.shape == blocked.shape and np.array_equal(got, ~blocked), \
        "0.1 m 격자를 다운샘플한 결과가 의도한 1 m 통행성과 다르다 (to_raw 검산 실패)"

    cells = place_stations(spec, topo)
    _check_dockable(cells, blocked)
    stations = {kind: [cell_to_xy(r, c) for r, c in pts] for kind, pts in cells.items()}

    zr0, zr1, zc0, zc1 = charge_zone_rect(spec, topo)
    zone = {"charge_zone": [{"id": "east",
                             "x0": round(zc0 - OFFSET_M, 1), "y0": float(zr0),
                             "x1": round(zc1 + 1 - OFFSET_M, 1), "y1": float(zr1 + 1)}],
            "meta": {"unit": "m",
                     "frame": "원본 0.1 m 맵 좌표계 (stations.json과 동일)",
                     "grid_1m": f"FMS 1 m 격자로 c={zc0}~{zc1}, r={zr0}~{zr1}",
                     "semantics": "존 안에 로봇 몸이 있으면 충전. 슬롯·레인 없음",
                     "source": f"map/synth_warehouse.py — 합성 창고 '{spec.name}' (S15P21A106-139)"}}
    stations["charge_zone"] = zone["charge_zone"]
    return raw, stations, zone, topo, blocked


def write_set(spec, out_dir):
    raw, stations, zone, topo, blocked = build_set(spec)
    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "occupancy_grid.npy"), raw)
    _dump(os.path.join(out_dir, "stations.json"), stations)
    _dump(os.path.join(out_dir, "charge_zone.json"), zone)
    topo.save(out_dir)
    _dump(os.path.join(out_dir, SPEC_FILE), spec.to_dict())
    return dict(out_dir=out_dir, shape=raw.shape, coarse=blocked.shape,
                free=int((~blocked).sum()), aisles=topo.n_aisles,
                stations=sum(len(v) for k, v in stations.items() if k != "charge_zone"),
                close_pairs=len(close_station_pairs(place_stations(spec, topo))))


def _dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def load_spec_file(map_dir):
    with open(os.path.join(map_dir, SPEC_FILE), encoding="utf-8") as f:
        return WarehouseSpec.from_dict(json.load(f))


# ------------------------------------------------------------
# 5) 프로파일
# ------------------------------------------------------------
# wallA 실측 프로파일 — 공식 맵(3_FMS/map)에서 잰 값. 링 영역 1 m 통행성이 정확히 일치한다.
# extra_blocks 는 파라메트릭 규칙으로 안 나오는 실측 구조물(기둥·검수대·모서리 벽) 목록이고,
# 무엇이 왜 여기 있는지는 docs/합성_창고_생성기.md §3 에 있다. 합성 창고는 이 목록이 비어 있다.
WALL_A_EXTRA_BLOCKS = (
    (40, 40, 21, 23), (72, 72, 21, 23),          # 검수(qc) 대 구조물 남·북
    (40, 43, 106, 108), (43, 43, 95, 105),       # 남동 모서리 벽 + 출고구 옆 구조물
    (56, 58, 20, 21), (56, 58, 26, 27),          # 서 밴드 중간 기둥열
    (56, 56, 25, 25), (58, 58, 25, 25),
    (56, 58, 31, 31), (56, 58, 99, 99),          # 랙 블록 양옆 기둥
    (56, 58, 104, 105), (56, 56, 103, 103), (58, 58, 103, 103),   # 충전 존 기둥 (x=104.1)
    (67, 73, 103, 108),                          # 북동 모서리 — 충전 존 위 폐쇄 구역
    (70, 71, 20, 30),                            # 북서 블록
)

WALL_A_STATION_LINES = (
    StationLine("induction", "S", 2, first=36, step=6),
    StationLine("consol", "S", 2, first=50, step=6),
    StationLine("packing", "S", 5, first=64, step=6),
    StationLine("vas", "S", 3, first=94, step=5),
    StationLine("input", "S", 1, first=32),
    StationLine("output", "S", 1, inset=3, first=94),
    StationLine("qc", "S", 1, inset=1, first=22),
    StationLine("input", "N", 1, inset=2, first=32),
    StationLine("output", "N", 1, first=94),
    StationLine("returns", "N", 2, first=36, step=6),
    StationLine("qc", "N", 1, first=22),
    StationLine("inbound_buf", "W", 3, inset=4, first=52, step=6),
    StationLine("charger", "E", 6, first=50, step=3),
    StationLine("charge_q", "E", 6, inset=3, first=50, step=3),
)


def wall_a_profile():
    """공식 맵 wallA 를 파라미터로 적은 것. raw_shape 은 공식 맵과 같게 둬 check_map_set.py 도 돈다."""
    return WarehouseSpec(
        name="wallA", n_aisles=11, aisle_pitch=6, aisle_half_width=1, aisle_len=21,
        band_s=7, band_n=6, band_w=12, band_e=10, origin=(40, 20),
        raw_shape=(1061, 1151),
        extra_blocks=WALL_A_EXTRA_BLOCKS, station_lines=WALL_A_STATION_LINES,
        charge_zone_col_inset=4, charge_zone_row_inset=1,
    )


# ------------------------------------------------------------
# 랙 변주 — 밴드·스테이션은 wallA 그대로, 랙 블록만 바꾼다
#
# θ 는 통로 단위 규칙이라(감도 실험 §0 실효 3개: wait_cost·loop_dir·loop_gain) 변인을 통로
# 기하 하나로 좁히면 wallA 대비 통제된 비교가 된다. 밴드 두께·스테이션 개수·충전 존까지 흔들면
# "θ 가 창고의 무엇에 반응했나"가 섞인다. 줄 배치만 wallA 의 절대 좌표(first=…)에서 자동 배치로
# 바꿨다 — 랙 블록 폭이 달라지면 절대 좌표가 맞지 않기 때문이다.
# ------------------------------------------------------------
RACK_VARIANT_STATION_LINES = (
    StationLine("induction", "S", 2),          # 남 밴드 바깥 줄 (wallA r40 작업 라인)
    StationLine("packing", "S", 5),
    StationLine("vas", "S", 3),
    StationLine("consol", "S", 2, inset=3),    # 남 밴드 안쪽 줄
    StationLine("input", "S", 1, inset=3),
    StationLine("output", "S", 1, inset=3),
    StationLine("returns", "N", 2),            # 북 밴드 바깥 줄
    StationLine("input", "N", 1),
    StationLine("output", "N", 1),
    StationLine("qc", "N", 1),
    StationLine("inbound_buf", "W", 3, inset=4),
    StationLine("qc", "W", 1, inset=4),
    StationLine("charger", "E", 6),
    StationLine("charge_q", "E", 6, inset=3),
)
# 통로 개수 / 중심 간격 / 통로 길이. wallA = (11, 6, 21) 이 이 격자 안에 들어 있다.
# 하한은 배치가 성립하는 선 — 통로 6개·간격 5 면 남 밴드 바깥 줄 10개가 간격 3 으로 겨우 들어가고,
# 통로 길이 17 이면 충전기 6개가 간격 3 으로 겨우 들어간다.
RACK_VARIANT_AISLES = (6, 8, 9, 11, 13, 14, 16)
RACK_VARIANT_PITCH = (5, 6, 7, 8)
RACK_VARIANT_LEN = (17, 21, 25, 29)


def rack_variant_spec(n_aisles, aisle_pitch, aisle_len, name=None):
    """랙 블록만 다른 wallA — 밴드·스테이션·충전 존은 공식 맵과 같은 값."""
    return WarehouseSpec(
        name=name or f"r{n_aisles}p{aisle_pitch}l{aisle_len}",
        n_aisles=n_aisles, aisle_pitch=aisle_pitch, aisle_half_width=1, aisle_len=aisle_len,
        band_s=7, band_n=6, band_w=12, band_e=10, origin=(40, 20), margin=2,
        station_lines=RACK_VARIANT_STATION_LINES,
        charge_zone_col_inset=4, charge_zone_row_inset=1,
    )


def rack_variant_grid(n, rng=None):
    """랙 격자에서 서로 다른 조합 n 개. rng 를 주면 그 시드로 고르고, 없으면 축을 고루 훑는다."""
    combos = [(a, p, ln) for a in RACK_VARIANT_AISLES
              for p in RACK_VARIANT_PITCH for ln in RACK_VARIANT_LEN]
    assert n <= len(combos), f"조합은 {len(combos)}개뿐이다 (요청 {n})"
    if rng is not None:
        idx = rng.choice(len(combos), size=n, replace=False)
        picked = [combos[int(i)] for i in sorted(idx)]
    else:
        step = len(combos) / n                       # 축을 고루 지나가도록 등간격
        picked = [combos[int(i * step)] for i in range(n)]
    return [rack_variant_spec(*c) for c in picked]


def random_spec(rng, name, seed=None):
    """합성 창고 하나 — wallA 를 중심으로 통로 수·간격·길이·밴드 두께를 흔든다.

    스테이션은 first 없이 놓아 창고 크기가 달라져도 자리를 잡는다. 쓰는 직선은 변마다
    정해 뒀다 — 남 2줄(inset 0·3), 북 1줄, 서 1줄, 동 2줄(충전기·대기열). 직선 사이를
    3칸 이상 띄우고 같은 직선은 슬롯을 나눠 쓰므로 2칸 차체가 겹치지 않는다
    (close_station_pairs 가 0). 밴드 두께 하한도 그 간격에서 나온다:

        남: aisle_buf 행(밴드 맨 안쪽)과 inset 3 줄이 3칸 떨어지려면 band_s >= 7
        북: aisle_buf 행이 밴드 안쪽 두 번째라 band_n >= 5

    구조물(extra_blocks)은 넣지 않는다 — 실측 창고의 잡동사니를 흉내 낼 근거가 없다.
    """
    n_aisles = int(rng.integers(6, 17))
    pitch = int(rng.integers(5, 9))
    aisle_len = int(rng.integers(14, 31))
    band_s = int(rng.integers(7, 11))
    band_n = int(rng.integers(5, 10))
    band_w = int(rng.integers(7, 15))
    band_e = int(rng.integers(8, 14))
    # 충전기·대기열은 랙 구간 행 길이 안에 간격 3 으로 들어가야 한다 (통로가 짧으면 줄인다)
    n_chg = min(int(rng.integers(3, 7)), max(2, (aisle_len - 1) // MIN_STATION_GAP))
    lines = (
        # 남 밴드 바깥 줄 (wallA 의 r40 작업 라인에 해당) — 하나의 직선을 나눠 쓴다
        StationLine("induction", "S", int(rng.integers(1, 4))),
        StationLine("packing", "S", int(rng.integers(2, 7))),
        StationLine("vas", "S", int(rng.integers(1, 4))),
        # 남 밴드 안쪽 줄
        StationLine("consol", "S", int(rng.integers(1, 4)), inset=3),
        StationLine("input", "S", 1, inset=3),
        StationLine("output", "S", 1, inset=3),
        # 북 밴드 바깥 줄
        StationLine("returns", "N", int(rng.integers(1, 4))),
        StationLine("input", "N", 1),
        StationLine("output", "N", 1),
        StationLine("qc", "N", 1),
        # 서 밴드 / 동 밴드
        StationLine("inbound_buf", "W", int(rng.integers(2, 5)), inset=4),
        StationLine("qc", "W", 1, inset=4),
        StationLine("charger", "E", n_chg),
        StationLine("charge_q", "E", n_chg, inset=3),
    )
    return WarehouseSpec(name=name, n_aisles=n_aisles, aisle_pitch=pitch,
                         aisle_half_width=1, aisle_len=aisle_len,
                         band_s=band_s, band_n=band_n, band_w=band_w, band_e=band_e,
                         origin=(4, 4), margin=2, station_lines=lines, seed=seed)


# ------------------------------------------------------------
# 6) 공식 맵과 대조
# ------------------------------------------------------------
def compare_with_official(map_dir, official_dir=None):
    """합성 세트 ↔ 공식 맵 — 링 영역 1 m 통행성과 토폴로지 5개 배열 차이.

    링 밖은 비교하지 않는다. wallA 의 북쪽 부속 구역(r74~88)은 창고 모형에 없기 때문이다.
    """
    from from_theta import extract_topology
    from map_loader import MAP_DIR, load_map, load_topology_spec

    official_dir = official_dir or MAP_DIR
    ref_free, ref_st, _ = load_map(official_dir)
    got_free, got_st, _ = load_map(map_dir)
    topo = load_topology_spec(map_dir)
    (r0, r1), (c0, c1) = topo.ring_rows, topo.ring_cols

    ring = np.zeros(ref_free.shape, dtype=bool)
    ring[r0:r1, c0:c1] = True
    if got_free.shape != ref_free.shape:
        print(f"[FAIL] 격자 크기 {got_free.shape} != 공식 {ref_free.shape}")
        return 1
    blk = int((ref_free & ~got_free & ring).sum())
    opn = int((~ref_free & got_free & ring).sum())
    print(f"링 {r0}~{r1 - 1} × {c0}~{c1 - 1} ({int(ring.sum())}칸) — "
          f"합성만 막힘 {blk} / 합성만 열림 {opn}")

    rt = extract_topology(ref_free, ref_st)
    gt = extract_topology(got_free, got_st, spec=topo)
    diffs = {}
    for attr in ("v_aisle_rank", "main_aisle", "loop_fwd", "junction"):
        d = int(((getattr(rt, attr) != getattr(gt, attr)) & ring).sum())
        diffs[attr] = d
    print("토폴로지 차이(링 안): " + ", ".join(f"{k} {v}" for k, v in diffs.items()))

    ref_kinds = {k.split("[")[0] for k in ref_st}
    got_kinds = {k.split("[")[0] for k in got_st}
    if ref_kinds - got_kinds:
        print(f"  없는 스테이션 종류: {sorted(ref_kinds - got_kinds)}")
    moved = sorted(k for k in set(ref_st) & set(got_st) if ref_st[k] != got_st[k])
    print(f"스테이션 종류 {len(got_kinds)}개, 공식과 칸이 다른 것 {len(moved)}개"
          + (f": {moved}" if moved else ""))
    ok = blk == 0 and opn == 0 and not any(diffs.values())
    print("[OK] 링 영역 재현 일치" if ok else "[DIFF] 위 값 확인")
    return 0 if ok else 2


# ------------------------------------------------------------
# 7) 인덱스 표
# ------------------------------------------------------------
def _charge_zone_capacity(free, map_dir, limit=80):
    """충전 존이 간격 2 로 앉힐 수 있는 최대 로봇 수 (map_loader.make_homes_zone 규칙)."""
    from map_loader import load_charge_zone, make_homes_zone
    zone = load_charge_zone(free, map_dir)
    if zone is None:
        return 0
    zone = zone & free
    cap = 0
    for n in range(2, limit + 1):
        try:
            make_homes_zone(free, zone, n)
        except AssertionError:
            break
        cap = n
    return cap


def survey(map_dir):
    """맵 세트 하나의 정적 사실 — 시뮬 없이 읽을 수 있는 것만."""
    from map_loader import load_map
    spec = load_spec_file(map_dir)
    free = load_map(map_dir, aisle_block=True)[0]
    cells = int(free.sum())
    fleet = max(1, round(cells / FLEET_CELLS_PER_ROBOT))
    return dict(name=spec.name, aisles=spec.n_aisles, pitch=spec.aisle_pitch,
                length=spec.aisle_len, shape=f"{free.shape[0]}×{free.shape[1]}",
                free=cells, fleet=fleet, capacity=_charge_zone_capacity(free, map_dir),
                in_band=THETA_FLEET_BAND[0] <= fleet <= THETA_FLEET_BAND[1])


def _sim_tasks_per_h(map_dir, sim_engine_dir):
    """INDEX_SIM 조건으로 한 번 돌려 tasks_per_h 만 뽑는다. 실패하면 None."""
    import subprocess
    a = INDEX_SIM
    cmd = [sys.executable, "sim_v2_tasks.py", "idx", str(a["robots"]), str(a["orders"]),
           str(a["seed"]), str(a["aisle_block"]), f"--order-gap={a['order_gap']}",
           f"--map-dir={os.path.abspath(map_dir)}"]
    env = dict(os.environ, SIM_NO_PLOT="1", PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(cmd, cwd=sim_engine_dir, env=env, timeout=300,
                           capture_output=True, text=True, encoding="utf-8")
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    for line in (p.stdout or "").splitlines():
        if line.startswith("[SUMMARY] "):
            return json.loads(line[len("[SUMMARY] "):])["tasks_per_h"]
    return None


def build_index(root, sim=False, jobs=8):
    """`<root>/README.md` 에 창고 목록 표를 쓴다. 폴더를 안 열고도 고를 수 있게.

    표를 손으로 쓰지 않는 이유는 단순하다 — 맵이 바뀌면 손으로 쓴 표는 바로 낡는다.
    """
    dirs = sorted(d for d in os.listdir(root)
                  if os.path.exists(os.path.join(root, d, SPEC_FILE)))
    rows = [survey(os.path.join(root, d)) for d in dirs]
    rows.sort(key=lambda r: (r["aisles"], r["pitch"], r["length"]))

    if sim:
        from concurrent.futures import ThreadPoolExecutor
        sim_dir = os.path.normpath(os.path.join(HERE, "..", "sim_engine"))
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            vals = list(pool.map(lambda r: _sim_tasks_per_h(os.path.join(root, r["name"]), sim_dir), rows))
        for r, v in zip(rows, vals):
            r["tph"] = v

    a = INDEX_SIM
    out = [
        "# 합성 창고 목록 (S15P21A106-139)",
        "",
        f"`map/synth_warehouse.py` 가 만든 창고 {len(rows)}개. 이 표도 생성물이다 —",
        "손으로 고치지 말고 `python synth_warehouse.py index synth` 로 다시 만든다.",
        "",
        "이름이 곧 파라미터다: `r13p7l25` = 통로 13개 · 중심 간격 7 · 통로 길이 25.",
        "",
        "| 열 | 뜻 |",
        "|---|---|",
        "| free | 통로차단 ON 에서 통행 가능한 1 m 칸 수 |",
        f"| 권장 대수 | free ÷ {FLEET_CELLS_PER_ROBOT} — 공식 맵과 같은 기하(r11p6l21)의 20대와 칸당 밀도를 맞춘 값. "
        "창고 크기가 다른데 대수를 고정하면 기하 차이와 혼잡도 차이가 섞인다 |",
        f"| 충전존 | 간격 2 로 앉힐 수 있는 최대 로봇 수 (권장 대수보다 커야 한다) |",
        f"| θ | 권장 대수가 θ 판정 가능 구간 {THETA_FLEET_BAND[0]}~{THETA_FLEET_BAND[1]}대 안인가 "
        "(대수별 결과 §4: 8대는 효과가 약하고 28대는 시드마다 부호가 갈린다) |",
    ]
    if sim:
        out.append(f"| tasks/h | 로봇 {a['robots']}대 · 주문 {a['orders']} · 간격 {a['order_gap']}틱 · "
                   f"시드 {a['seed']} · 통로차단 ON 에서 1회 실측. **창고 난이도 비교용 고정 조건**이지 "
                   "권장 조건이 아니다 |")
    head = "| 창고 | 통로 | 간격 | 길이 | 격자 | free | 권장 대수 | 충전존 | θ |"
    sep = "|---|---:|---:|---:|---|---:|---:|---:|:-:|"
    if sim:
        head += " tasks/h |"
        sep += "---:|"
    out += ["", head, sep]
    for r in rows:
        line = (f"| `{r['name']}` | {r['aisles']} | {r['pitch']} | {r['length']} | {r['shape']} | "
                f"{r['free']} | {r['fleet']} | {r['capacity']} | {'O' if r['in_band'] else '—'} |")
        if sim:
            line += f" {'' if r.get('tph') is None else format(r['tph'], '.1f')} |"
        out.append(line)

    outside = [r["name"] for r in rows if not r["in_band"]]
    short = [r for r in rows if r["capacity"] < r["fleet"]]
    usable = [r for r in rows if r["in_band"] and r["capacity"] >= r["fleet"]]
    out += ["", "## 라벨링에 바로 쓸 수 있는 창고", "",
            f"권장 대수가 θ 구간 안이고 충전 존이 그 대수를 앉힐 수 있는 창고가 **{len(usable)}개**다 "
            f"(통로 수 {sorted({r['aisles'] for r in usable})} 를 전부 덮는다). 나머지는 아래 이유로 걸린다."]
    if outside:
        out += ["", f"**θ 구간 밖 {len(outside)}개** — 권장 대수가 {THETA_FLEET_BAND[1]}대를 넘는다. "
                    "라벨링 대상에서 빼거나 대수를 구간 안으로 낮춰 쓴다: "
                    + ", ".join(f"`{n}`" for n in outside)]
    if short:
        out += ["", f"**충전 존 용량 부족 {len(short)}개** — 권장 대수를 간격 2 로 못 앉힌다. "
                    "통로가 짧아(`l17`) 존이 작은데 창고는 넓은 조합이다: "
                    + ", ".join(f"`{r['name']}`(권장 {r['fleet']}/수용 {r['capacity']})" for r in short)]
    out += ["", "자세한 설계는 [합성 창고 생성기](../../docs/합성_창고_생성기.md).", ""]

    path = os.path.join(root, INDEX_FILE)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    return path, len(rows)


# ------------------------------------------------------------
# 8) CLI
# ------------------------------------------------------------
def _main(argv=None):
    p = argparse.ArgumentParser(description="합성 창고 생성기 (S15P21A106-139)")
    p.add_argument("mode", choices=("racks", "wallA", "random", "check", "index"),
                   help="racks = 랙 블록만 변주(권장) / wallA = 실측 재현 / "
                        "random = 밴드·스테이션까지 변주 / check = 공식 맵과 대조 / "
                        "index = 창고 목록 표(README.md) 생성")
    p.add_argument("out", help="생성 모드는 출력 폴더, check/index 는 맵 세트 폴더")
    p.add_argument("--n", type=int, default=12, help="만들 창고 수 (racks/random)")
    p.add_argument("--seed", type=int, default=None,
                   help="racks: 격자에서 무작위로 고를 때의 시드 (생략하면 축을 고루 훑는 고정 목록). "
                        "random: 필수 성격의 시드, 기본 0")
    p.add_argument("--sim", action="store_true",
                   help="index: 창고마다 시뮬 1회를 돌려 tasks/h 열을 채운다 (창고당 수 초)")
    p.add_argument("--jobs", type=int, default=8, help="index --sim 병렬 프로세스 수")
    a = p.parse_args(argv)

    if a.mode == "check":
        return compare_with_official(a.out)
    if a.mode == "index":
        path, n = build_index(a.out, sim=a.sim, jobs=a.jobs)
        print(f"창고 {n}개 → {path}")
        return 0
    if a.mode == "wallA":
        print(write_set(wall_a_profile(), a.out))
        return 0
    if a.mode == "racks":
        rng = None if a.seed is None else np.random.default_rng(a.seed)
        for spec in rack_variant_grid(a.n, rng):
            print(write_set(spec, os.path.join(a.out, spec.name)))
        return 0
    rng = np.random.default_rng(a.seed or 0)
    for i in range(a.n):
        name = f"w{a.seed or 0:03d}_{i:02d}"
        print(write_set(random_spec(rng, name, seed=a.seed or 0), os.path.join(a.out, name)))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
