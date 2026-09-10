# -*- coding: utf-8 -*-
# ============================================================
# AI 입력 텐서 생성 — 39채널 + 운영조건 9개 (S15P21A106-134)
#
# 명세: 5_Docs/AI/AI입출력명세서.md §4(창고 18ch) §5(짐 흐름 6ch) §6(통로 15ch)
#       §7(운영조건 9) §8(합치기) §9(정규화)
# 계약: contracts/guidance_types.py GuidanceInput
#
# 토폴로지는 sim_engine/from_theta.py 의 extract_topology() 를 재사용한다.
# 명세 §6-3이 요구하는 "규칙 기반 자동 추출"은 아니지만, 지금 그렇게 가는 이유:
#
#   1. 일반 규칙(run length 로 통로 축 판정 → 연결성분으로 묶기 → 큰 통로 폭
#      임계 → 순환로는 영역을 가두는 성분)을 구현해 실측했으나 이 맵에서
#      결과가 깨졌다. 세로 통로 50개(기대 11개), 순환로 0개. 벽으로 둘러싸여
#      도달 불가한 남·북 구역을 걸러낸 뒤에도 그렇다 — 북쪽 개방 구역이 큰
#      통로로 잡혀 순환로가 링을 이루지 못한다. 임계값 조정으로 넘길 문제가
#      아니라 규칙 자체를 더 설계해야 한다.
#   2. from_theta 와 **같은 토폴로지를 보게 된다.** AI가 배우는 구조와 실제
#      비용을 만드는 구조가 어긋나면 학습이 무의미해진다. 별도 추출기를 두면
#      130이 발견한 "맵 복사본 어긋남"과 같은 부류의 사고가 반복된다.
#
# 2026-09-08(S15P21A106-139): wallA 전용이던 제약이 풀렸다. 추출기를 일반화한 게
# 아니라 **창고를 만드는 쪽이 토폴로지를 같이 낸다** — map_dir 의 topology.json 을
# extract_topology(spec=…) 로 넘긴다. 위 이유 2는 그대로다(시뮬 비용과 AI 입력이 같은
# 스펙 한 장을 본다). 공식 맵에는 그 파일이 없어 wallA 상수로 떨어진다.
# docs/합성_창고_생성기.md · map/synth_warehouse.py
# ============================================================
from collections import deque
import os
import sys

import numpy as np

_FMS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SIM_ENGINE = os.path.join(_FMS_ROOT, "sim_engine")
for _p in (_FMS_ROOT, _SIM_ENGINE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from contracts.guidance_types import GuidanceInput  # noqa: E402
from from_theta import extract_topology  # noqa: E402
from map_loader import load_charge_zone, load_map, load_topology_spec  # noqa: E402

# 방향 규약 — 명세 §3-2 (북0 동1 남2 서3), §14-1 (y가 커지면 북쪽)
DIR_N, DIR_E, DIR_S, DIR_W = 0, 1, 2, 3
DIR_COUNT = 4
DELTAS = ((1, 0), (0, 1), (-1, 0), (0, -1))   # (dr, dc)

STATIC_CHANNELS = 18
TASK_CHANNELS = 6
TOPOLOGY_CHANNELS = 15
SCENARIO_SIZE = 9

# 구역 채널(명세 §4 ch6~12) ← 스테이션 종류 매핑.
# ⚠️ 팀 합의 필요. qc를 검수로, returns를 출고로 본 것은 이름에서 유추한 것이다.
ZONE_STATION_KINDS = {
    "zone_inbound": ("input", "inbound_buf"),
    "zone_receiving": ("qc",),
    "zone_storage": ("aisle_buf",),
    "zone_picking": ("induction",),
    "zone_packing": ("packing", "consol", "vas"),
    "zone_outbound": ("output", "returns"),
    "zone_charging": ("charger", "charge_q"),
}
ZONE_ORDER = ("zone_inbound", "zone_receiving", "zone_storage", "zone_picking",
              "zone_packing", "zone_outbound", "zone_charging")

# 픽업 자리 = 랙 통로 버퍼 (명세 §4 ch17 dist_pick)
PICK_KIND = "aisle_buf"

# 운영조건 기본값 (명세 §7). V1은 적재·공차 속도를 같게 둔다 (§7-1).
AMR_SPEED_LOADED = 1.0
AMR_SPEED_EMPTY = 1.0
AMR_WIDTH_M = 0.641
AMR_LENGTH_M = 1.44

# 주문 분포 — sim_v2_tasks.py 의 spawn_order / spawn_inbound 규칙과 동일해야 한다.
# 어긋나면 task_profile 이 시뮬이 실제로 만드는 흐름과 다른 것을 말하게 된다.
K_LINE_P = (0.5, 0.3, 0.2)        # 주문당 상품 라인 수 {1,2,3} 분포


def _kind_cells(free, st_cell, kinds):
    mask = np.zeros(free.shape, dtype=bool)
    for name, rc in st_cell.items():
        if name.split("[")[0] in kinds and free[rc]:
            mask[rc] = True
    return mask


def _cells_of(st_cell, kind):
    """`kind[i]` 형태 이름의 칸을 i 순서로."""
    out = []
    i = 0
    while f"{kind}[{i}]" in st_cell:
        out.append(st_cell[f"{kind}[{i}]"])
        i += 1
    return out


def multi_source_dist(free, sources):
    """free 격자 위 BFS 거리(칸 수). 도달 불가 -1."""
    dist = np.full(free.shape, -1, dtype=np.int32)
    H, W = free.shape
    q = deque()
    for r, c in zip(*np.nonzero(sources & free)):
        r, c = int(r), int(c)
        dist[r, c] = 0
        q.append((r, c))
    while q:
        r, c = q.popleft()
        base = dist[r, c]
        for dr, dc in DELTAS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < H and 0 <= cc < W and free[rr, cc] and dist[rr, cc] < 0:
                dist[rr, cc] = base + 1
                q.append((rr, cc))
    return dist


def _normalized_dist(free, sources, diag):
    """명세 §9 — 거리 ÷ 창고 대각선 길이. 도달 불가·비통행 칸은 1.0(가장 멈)."""
    dist = multi_source_dist(free, sources)
    out = np.where(dist < 0, 1.0, dist / diag).astype(np.float32)
    return np.clip(out, 0.0, 1.0)


def build_static_map(free, st_cell, topo, charge_zone=None):
    """명세 §4 — 창고 생김새 18채널."""
    H, W = free.shape
    diag = float(np.hypot(H, W))
    ch = np.zeros((STATIC_CHANNELS, H, W), dtype=np.float32)

    ch[0] = ~free                                        # obstacle
    ch[1] = free                                         # walkable
    ch[2] = topo.main_aisle & free                       # main_aisle
    ch[3] = (topo.v_aisle_rank >= 0) & ~topo.main_aisle  # sub_aisle (랙 사이)
    ch[4] = topo.junction & free                         # intersection
    ch[5] = topo.station & free                          # station (충전 제외)

    zones = {}
    for i, key in enumerate(ZONE_ORDER):
        mask = _kind_cells(free, st_cell, ZONE_STATION_KINDS[key])
        if key == "zone_charging" and charge_zone is not None:
            mask |= charge_zone & free
        zones[key] = mask
        ch[6 + i] = mask                                 # ch6~12 구역 (One-Hot, §4 주의)

    degree = np.zeros((H, W), dtype=np.float32)
    for d in range(DIR_COUNT):
        dr, dc = DELTAS[d]
        shifted = np.roll(free, (-dr, -dc), axis=(0, 1))
        if dr:
            shifted[-1 if dr > 0 else 0, :] = False
        if dc:
            shifted[:, -1 if dc > 0 else 0] = False
        degree += shifted
    ch[13] = np.where(free, degree / DIR_COUNT, 0.0)     # §4 ch13 degree

    ch[14] = _normalized_dist(free, zones["zone_inbound"], diag)
    ch[15] = _normalized_dist(free, zones["zone_outbound"], diag)
    ch[16] = _normalized_dist(free, zones["zone_charging"], diag)
    ch[17] = _normalized_dist(free, _kind_cells(free, st_cell, (PICK_KIND,)), diag)
    return ch


def _expected_unique_lines(n_aisle, k_probs=K_LINE_P):
    """주문 하나가 만드는 태스크 수의 기대값.

    sim_v2 는 상품 라인 k개를 중복 허용으로 뽑고 같은 통로는 토트 1개로 합친다.
    22개 중 k개를 복원추출했을 때 서로 다른 통로 수의 기대값 = n(1-((n-1)/n)^k).
    """
    return sum(p * n_aisle * (1.0 - ((n_aisle - 1) / n_aisle) ** k)
               for k, p in enumerate(k_probs, start=1))


def od_distribution(st_cell):
    """sim_v2 의 주문·입고 규칙에서 유도한 (출발칸, 도착칸, 확률) 목록.

    출고  aisle_buf[a] → packing[p]   (a·p 균등)
    입고  inbound_buf[i] → aisle_buf[a] (i·a 균등)
    가중치는 도착률이 같으므로(ORDER_MEAN_GAP = INBOUND_MEAN_GAP, N_INBOUND =
    N_ORDERS) 주문 1건당 태스크 수의 비율로 준다.
    """
    aisle = _cells_of(st_cell, "aisle_buf")
    pack = _cells_of(st_cell, "packing")
    inbound = _cells_of(st_cell, "inbound_buf")
    if not (aisle and pack and inbound):
        raise ValueError("aisle_buf / packing / inbound_buf 스테이션을 못 찾음")

    w_out = _expected_unique_lines(len(aisle))
    w_in = 1.0
    total = w_out + w_in

    pairs = []
    p_out = (w_out / total) / (len(aisle) * len(pack))
    for a in aisle:
        for p in pack:
            pairs.append((a, p, p_out))
    p_in = (w_in / total) / (len(inbound) * len(aisle))
    for i in inbound:
        for a in aisle:
            pairs.append((i, a, p_in))
    return pairs


def accumulate_flow(free, dist, start, prob, out):
    """start 에서 목표로 가는 최단 흐름을 out(4, H, W)에 누적한다.

    명세 §5-2는 "최단경로가 여러 개면 항상 같은 방식으로 하나를 고른다"고 한다.
    한 경로만 고르면 **그 경로가 지나는 칸에만** 수요가 찍힌다 — 실측에서 북행
    수요가 17칸에만 몰렸다. 실제로는 같은 OD 를 잇는 최단경로가 여러 통로에 걸쳐
    있고, "이 칸을 지날 짐이 얼마나"(§5 채널 정의)는 그 전체에 퍼져야 맞다.

    그래서 모든 최단경로에 확률을 **균등 분배**한다. 갈림길마다 감소 이웃 수로
    나눠 흘려보낸다. 규칙은 고정돼 있고(§5-2 요구) 어느 한 통로에 몰리지 않는다.

    참고 — 방향별 **총합**은 어느 경로를 골라도 같다. 격자 최단경로는 북·동
    걸음 수가 OD 의 변위로 정해지기 때문이다. 이 함수가 바꾸는 건 공간 분포다.
    """
    d0 = int(dist[start])
    if d0 < 0:
        return
    buckets = {d0: {start: prob}}
    for level in range(d0, 0, -1):
        layer = buckets.pop(level, None)
        if layer:
            _push_layer(free, dist, level, layer, buckets, out)


def _descending_neighbours(free, dist, cell, level):
    """cell 에서 목표에 한 칸 더 가까운 이웃들 — 최단경로의 다음 걸음 후보."""
    H, W = free.shape
    r, c = cell
    found = []
    for d, (dr, dc) in enumerate(DELTAS):
        rr, cc = r + dr, c + dc
        if 0 <= rr < H and 0 <= cc < W and free[rr, cc] and dist[rr, cc] == level - 1:
            found.append((d, rr, cc))
    return found


def _push_layer(free, dist, level, layer, buckets, out):
    """거리 level 인 칸들의 질량을 다음 층으로 균등 분배한다."""
    nxt = buckets.setdefault(level - 1, {})
    for cell, mass in layer.items():
        nbrs = _descending_neighbours(free, dist, cell, level)
        if not nbrs:
            continue
        share = mass / len(nbrs)
        for d, rr, cc in nbrs:
            out[d][cell] += share
            nxt[(rr, cc)] = nxt.get((rr, cc), 0.0) + share


def build_task_profile(free, st_cell):
    """명세 §5 — 짐 흐름 6채널. 시뮬을 돌리지 않고 주문 정보만으로 계산한다(§5-2)."""
    H, W = free.shape
    ch = np.zeros((TASK_CHANNELS, H, W), dtype=np.float32)
    pairs = od_distribution(st_cell)

    targets = sorted({dst for _, dst, _ in pairs})
    dist_to = {t: multi_source_dist(free, _one_hot(free.shape, t)) for t in targets}

    for src, dst, prob in pairs:
        ch[0][src] += prob                                # pickup_density
        ch[1][dst] += prob                                # dropoff_density
        accumulate_flow(free, dist_to[dst], src, prob, ch[2:6])   # demand_dir 북동남서

    for i in (0, 1):
        s = ch[i].sum()
        if s > 0:
            ch[i] /= s
    flow = ch[2:6].sum()
    if flow > 0:
        ch[2:6] /= flow                                   # §5-2 전체 합 1
    return ch


def _one_hot(shape, cell):
    mask = np.zeros(shape, dtype=bool)
    mask[cell] = True
    return mask


def build_topology_tensor(free, topo):
    """명세 §6 — 통로 구조 15채널."""
    H, W = free.shape
    ch = np.zeros((TOPOLOGY_CHANNELS, H, W), dtype=np.float32)
    rank = topo.v_aisle_rank
    is_v = rank >= 0

    ch[0] = is_v                                          # 세로 통로
    ch[1] = topo.main_aisle & ~is_v                       # 가로 통로 (남·북 밴드)
    max_rank = int(rank.max()) if is_v.any() else 0
    ch[2] = np.where(is_v, rank / max(max_rank, 1), 0.0)  # §9 통로 번호 ÷ 최대 번호

    on_loop = topo.loop_fwd >= 0
    ch[3] = on_loop                                       # 순환로
    for d in range(DIR_COUNT):
        ch[4 + d] = on_loop & (topo.loop_fwd == d)        # ch4~7 시계 방향
        ch[8 + d] = topo.station_dir == d                 # ch8~11 작업자리 진입 방향

    # ch12~14 — 통로 번호의 나머지. §6-2: 정규화된 번호에서 짝·홀을 알아내기
    # 어려우므로 따로 준다.
    ch[12] = is_v & (rank % 2 == 1)                       # rank_mod2
    ch[13] = is_v & (rank % 3 == 1)                       # rank_mod3_a
    ch[14] = is_v & (rank % 3 == 2)                       # rank_mod3_b
    return ch


def build_scenario(free, n_agents, order_rate,
                   amr_speed_loaded=AMR_SPEED_LOADED, amr_speed_empty=AMR_SPEED_EMPTY,
                   amr_width=AMR_WIDTH_M, amr_length=AMR_LENGTH_M):
    """명세 §7 — 운영조건 9개. order_rate 단위는 '하루 주문 건수'."""
    H, W = free.shape
    walkable = int(free.sum())
    if walkable == 0:
        raise ValueError("통행 가능한 칸이 없음")
    return np.array([
        float(n_agents),                    # 0 n_agents
        float(order_rate),                  # 1 order_rate
        n_agents / walkable,                # 2 robot_density (§9)
        walkable / float(H * W),            # 3 free_ratio
        W / float(H),                       # 4 map_aspect_ratio (§9 비율로)
        float(amr_speed_loaded),            # 5
        float(amr_speed_empty),             # 6
        float(amr_width),                   # 7
        float(amr_length),                  # 8
    ], dtype=np.float32)


def build_guidance_input(n_agents, order_rate, sim_engine_dir=_SIM_ENGINE,
                         map_dir=None, aisle_block=False, **amr):
    """창고 + 운영조건 → GuidanceInput (명세 §8 순서: 생김새 → 짐 흐름 → 통로 구조).

    맵은 map_loader.load_map 을, 충전 존은 map_loader.load_charge_zone 을 그대로
    쓴다. 시뮬과 다른 로더를 두면 격자가 어긋난다
    (docs/맵_충전존.md#맵-불일치와-동기화-결정).

    `map_dir` 이 합성 창고면 토폴로지도 그 세트의 topology.json 에서 온다 (S15P21A106-139).
    공식 맵에는 그 파일이 없어 wallA 상수로 떨어지므로 기존 결과는 그대로다.
    """
    if map_dir is None:
        map_dir = os.path.join(_FMS_ROOT, "map")          # 공식 맵 폴더 (= map_loader.MAP_DIR)
    free, st_cell, _ = load_map(map_dir, aisle_block)     # sim_engine_dir 은 호환용(맵 복사본 제거됨)
    topo = extract_topology(free, st_cell, spec=load_topology_spec(map_dir))
    charge_zone = load_charge_zone(free, map_dir)
    return GuidanceInput(
        static_map=build_static_map(free, st_cell, topo, charge_zone),
        task_profile=build_task_profile(free, st_cell),
        topology_tensor=build_topology_tensor(free, topo),
        scenario=build_scenario(free, n_agents, order_rate, **amr),
    )


def stack_channels(inp):
    """명세 §8 — 생김새 18 + 짐 흐름 6 + 통로 구조 15 = (39, H, W)."""
    return np.concatenate([inp.static_map, inp.task_profile, inp.topology_tensor], axis=0)


def _main():
    inp = build_guidance_input(n_agents=10, order_rate=40)
    tensor = stack_channels(inp)
    print(f"static_map      {inp.static_map.shape}")
    print(f"task_profile    {inp.task_profile.shape}")
    print(f"topology_tensor {inp.topology_tensor.shape}")
    print(f"scenario        {inp.scenario.shape}  {np.round(inp.scenario, 4).tolist()}")
    print(f"합치면          {tensor.shape}\n")
    names = ("obstacle walkable main_aisle sub_aisle intersection station "
             "zone_inbound zone_receiving zone_storage zone_picking zone_packing "
             "zone_outbound zone_charging degree dist_inbound dist_outbound "
             "dist_charger dist_pick pickup_density dropoff_density "
             "demand_N demand_E demand_S demand_W v_aisle h_aisle aisle_rank loop "
             "loop_N loop_E loop_S loop_W entry_N entry_E entry_S entry_W "
             "rank_mod2 rank_mod3_a rank_mod3_b").split()
    for i, name in enumerate(names):
        c = tensor[i]
        nz = int((c != 0).sum())
        print(f"  {i:2d} {name:16s} 0이 아닌 칸 {nz:6d}  합 {c.sum():10.4f}  "
              f"최대 {c.max():.4f}")


if __name__ == "__main__":
    _main()
