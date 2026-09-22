# -*- coding: utf-8 -*-
"""`fms_stream` 의 백엔드 주문 변환 — 순수 함수 셋.

파일도 지도도 Isaac 도 안 쓴다. 변환 규칙이 FMS
(`3_FMS/sim_engine/order_stream.py`)와 같은 답을 내는지만 본다.

    python3 -m pytest path/test_fms_stream_json.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fms_stream as FS                                       # noqa: E402

DT = 0.2777777777777778          # pitch 1.0 / (0.9 x 4)
RACKS = {"A1": 0, "A2": 0, "B1": 1, "C3": 2}


# ── 도착 틱 ──────────────────────────────────────────────────────────
def test_arrival_tick_converts_seconds_to_our_ticks():
    # 백엔드는 **초**로 보낸다. CSV 의 created_tick 과 달리 환산이 한 번이다.
    assert FS._arrival_tick({"ordered_at_s": 0}, DT, None, 1000) == 0
    assert FS._arrival_tick({"ordered_at_s": 100}, DT, None, 1000) == 360


def test_arrival_tick_drops_orders_outside_the_window():
    assert FS._arrival_tick({"ordered_at_s": 1000}, DT, None, 100) is None


def test_window_start_shifts_but_only_when_given():
    """host-orch 가 이미 0 기준으로 당겨 준 목록에 또 빼면 전부 음수가 된다."""
    od = {"ordered_at_s": 50}
    assert FS._arrival_tick(od, DT, None, 10_000) == 180
    assert FS._arrival_tick(od, DT, 40, 10_000) == 36        # (50-40)/0.2778
    assert FS._arrival_tick(od, DT, 60, 10_000) is None      # 음수 -> 버린다


# ── 랙 -> 버퍼 ───────────────────────────────────────────────────────
def test_same_buffer_lines_are_summed():
    # A1 · A2 가 같은 버퍼 0 이면 qty 가 합쳐진다 (order_stream.py:259 와 같다)
    group, bad = FS._group_by_buffer(
        [{"rack_id": "A1", "qty": 3}, {"rack_id": "A2", "qty": 4}], RACKS)
    assert group == {0: 7}
    assert bad == []


def test_qty_defaults_to_one():
    group, bad = FS._group_by_buffer([{"rack_id": "B1"}], RACKS)
    assert group == {1: 1}
    assert bad == []


def test_unknown_rack_drops_the_whole_order():
    """일부만 실으면 수요가 **조용히** 줄어 비교가 깨진다. 그래서 전부 버린다."""
    group, bad = FS._group_by_buffer(
        [{"rack_id": "A1", "qty": 1}, {"rack_id": "ZZ9", "qty": 1}], RACKS)
    assert group == {}
    assert bad == ["ZZ9"]


# ── 토트 묶기 ────────────────────────────────────────────────────────
def test_totes_round_up_per_buffer():
    # ceil(합 / tote_units) — order_stream.py:260 와 같은 식
    assert FS._totes({0: 10}, 10) == [(0, 1)]
    assert FS._totes({0: 11}, 10) == [(0, 2)]
    assert FS._totes({0: 1}, 10) == [(0, 1)]


def test_totes_are_sorted_by_buffer():
    assert FS._totes({2: 1, 0: 1, 1: 1}, 10) == [(0, 1), (1, 1), (2, 1)]


def test_tote_units_zero_means_one_tote_per_buffer():
    assert FS._totes({0: 999}, 0) == [(0, 1)]


# ── 주문 목록 꺼내기 ─────────────────────────────────────────────────
def test_scenario_orders_accepts_the_three_shapes(tmp_path):
    """Start 페이로드 통째 · scenario.json · 생성기 산출물 — 셋 다 받는다."""
    import json
    want = [{"order_id": 1, "ordered_at_s": 0, "lines": []}]
    for name, doc in (
            ("start.json", {"run_id": "r", "scenario": {"orders": {"outbound": want}}}),
            ("scenario.json", {"orders": {"outbound": want}}),
            ("orders.json", {"meta": {}, "outbound": want}),
            ("bare.json", want)):
        p = tmp_path / name
        p.write_text(json.dumps(doc), encoding="utf-8")
        assert FS._scenario_orders(str(p)) == want, name


def test_scenario_orders_rejects_a_payload_without_orders(tmp_path):
    import json
    import pytest
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"run_id": "r"}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        FS._scenario_orders(str(p))


# ── 대형 주문 제외 (2026-09-23) ───────────────────────────────────────
#   이산은 토트 합계가 `MAX_ORDER_TOTES` 를 넘는 주문을 **통째로** 뺀다
#   (팔레트 흐름이라 시뮬 밖, 2026-09-14 결정). 우리는 안 뺐다 — 그래서
#   **물리 수요만 조용히 더 컸다.** 로그에도 결과에도 안 남았다.
def test_max_order_totes_is_read_from_upstream_not_copied():
    """값을 베끼면 상류가 바뀔 때 조용히 갈린다 — `pibt_core_v2` 와 같은 이유.

    상류를 못 찾으면 0(= 안 거름)을 주되 **소리내어** 알린다. 그 경우 이 테스트는
    건너뛴다 — sim_engine 이 없는 기계에서 실패로 잡을 일이 아니다.
    """
    n = FS.max_order_totes()
    if n == 0:
        import pytest
        pytest.skip("3_FMS/sim_engine 이 없다 — 상류를 못 읽는 환경")
    import order_stream as OS          # max_order_totes() 가 sys.path 를 이미 깔았다
    assert n == OS.MAX_ORDER_TOTES, "상류에서 읽지 않고 사본을 두면 조용히 갈린다"


def test_oversize_orders_are_dropped_whole_like_the_discrete_side():
    """일부만 싣지 않는다 — `_group_by_buffer` 가 랙을 못 찾을 때와 같은 규칙.

    토트 수 = ceil(qty / tote_units) 이므로 tote_units=1 이면 qty 가 곧 토트다.
    """
    n = FS.max_order_totes()
    if n == 0:
        import pytest
        pytest.skip("3_FMS/sim_engine 이 없다")
    # 상한 바로 아래 / 바로 위
    ok = _totes_of({"A1": n})
    over = _totes_of({"A1": n + 1})
    assert sum(c for _, c in ok) == n
    assert sum(c for _, c in over) == n + 1
    # 여러 버퍼로 흩어져도 **합계**로 판정한다 — 버퍼별이 아니다
    split = _totes_of({"A1": n, "B1": 1})
    assert sum(c for _, c in split) == n + 1


def _totes_of(qty_by_rack, tote_units=1):
    """{랙: qty} → [(버퍼, 토트수)]. 상류 `_parse_order` 와 같은 식."""
    lines = [{"rack_id": r, "qty": q} for r, q in qty_by_rack.items()]
    group, bad = FS._group_by_buffer(lines, RACKS)
    assert not bad
    return FS._totes(group, tote_units)
