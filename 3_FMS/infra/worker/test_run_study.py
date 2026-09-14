# -*- coding: utf-8 -*-
"""θ 탐색 워커의 맵 세트 연결 검사 (S15P21A106-183).

시뮬·Optuna storage 없이 인자 파싱과 meta 조립만 본다.
`3_FMS/infra/worker` 에서 `python -m pytest -q`.

못 박는 것 두 가지.

1. **공식 맵 경로는 안 변한다** — `--map-dir` 을 안 주면 시뮬에 넘기는 인자가 비어 있고
   meta 에 `map_dir` 키가 안 붙는다. 기존 study 재실행이 같은 θ 를 낸다.
2. **합성 창고는 그 맵의 충전 존이 상한이다** — wallA 상수 28 을 쓰면, 존이 24 인 창고에
   26 대를 걸어 두고 컨테이너가 다 뜬 뒤에야 시뮬 assert 로 죽는다.
3. **적재량이 탐색 조건에 남는다** (S15P21A106-192) — `--capacity` 를 안 넘기면 운영이
   6 토트인데 탐색은 1 토트로 돈다. 실측 차이가 455.1 vs 824.9 tasks_per_h 라 다른 θ 가 나온다.
   여기서 `capacity` 는 토트 수고, 충전 존 상한은 `zone_cap` 으로 구분해 부른다.
4. **부하는 실시간으로 고정된다** (S15P21A106-194) — 시뮬의 `--order-gap` 은 틱이고 틱 길이는
   속도·틱 모델이 정한다. 계약 v3.6 에서 1칸이 4틱이 되며 같은 "15" 가 15초 → 3.75초로 바뀌었다.
   워커는 `--arrival-s`(초)로 받아 `초/dt` 를 넘기므로, 틱 모델이 또 바뀌어도 부하는 그대로다.
"""
import json
import os
import sys
from types import SimpleNamespace

import pytest

optuna = pytest.importorskip("optuna", reason="워커 의존성 (infra/requirements.txt)")

HERE = os.path.dirname(os.path.abspath(__file__))
FMS_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
SIM_ENGINE = os.path.join(FMS_ROOT, "sim_engine")
SYNTH = os.path.join(FMS_ROOT, "map", "synth")
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import run_study as rs  # noqa: E402

BASE = ["--study", "t", "--robots", "12", "--orders", "60",
        "--sim-engine", SIM_ENGINE, "--fms-root", FMS_ROOT]
# map/synth/README.md 표의 실측값 (창고 이름이 곧 파라미터: 통로·간격·길이)
SYNTH_CASES = [("r6p5l17", 13, 24), ("r11p6l21", 20, 30), ("r16p5l17", 21, 24)]

pytestmark = pytest.mark.skipif(not os.path.isdir(SYNTH),
                                reason="합성 창고 세트가 없다 (map/synth_warehouse.py racks)")


def _args(*extra):
    return rs.parse_args(BASE + list(extra))


class TestOfficialMapUnchanged:
    def test_no_map_dir_means_no_extra_args(self):
        a = _args()
        assert a.map_dir is None
        assert a.extra_args == ()          # 시뮬 호출 인자가 기존과 한 글자도 다르지 않다

    def test_meta_has_no_map_dir_key(self):
        assert "map_dir" not in _meta(_args())["condition"]

    def test_wall_a_capacity_constant_still_applies(self):
        _args("--robots", "28")            # 계약 §1 상한 = 통과
        with pytest.raises(SystemExit):
            _args("--robots", "29")


class TestSyntheticWarehouse:
    @pytest.mark.parametrize("name,fleet,zone_cap", SYNTH_CASES)
    def test_extra_args_carry_the_map(self, name, fleet, zone_cap):
        a = _args("--map-dir", os.path.join(SYNTH, name), "--robots", str(fleet))
        assert a.extra_args == (f"--map-dir={a.map_dir}",)
        assert os.path.isabs(a.map_dir)

    @pytest.mark.parametrize("name,fleet,zone_cap", SYNTH_CASES)
    def test_capacity_comes_from_that_map(self, name, fleet, zone_cap):
        """상한은 wallA 상수가 아니라 그 창고의 충전 존이다."""
        assert rs.charge_zone_capacity(os.path.join(SYNTH, name), SIM_ENGINE) == zone_cap
        _args("--map-dir", os.path.join(SYNTH, name), "--robots", str(zone_cap))
        with pytest.raises(SystemExit):
            _args("--map-dir", os.path.join(SYNTH, name), "--robots", str(zone_cap + 1))

    def test_meta_records_a_portable_path(self):
        """절대 경로를 박으면 다른 머신·컨테이너에서 호출을 복원할 수 없다."""
        a = _args("--map-dir", os.path.join(SYNTH, "r11p6l21"), "--robots", "20")
        assert a.map_ref == "map/synth/r11p6l21"
        assert _meta(a)["condition"]["map_dir"] == "map/synth/r11p6l21"

    def test_missing_folder_is_rejected_before_the_study(self):
        with pytest.raises(SystemExit):
            _args("--map-dir", os.path.join(SYNTH, "없는창고"))


class TestToteCapacity:
    """적재량(계약 v2.6 --capacity). 기본값 1 은 -183 이전 실행과 글자 단위로 같아야 한다."""

    def test_default_is_one_and_invisible(self):
        a = _args()
        assert a.capacity == 1
        assert a.extra_args == ()
        assert "capacity" not in _meta(a)["condition"]

    def test_value_reaches_the_sim(self):
        a = _args("--capacity", "6")
        assert a.extra_args == ("--capacity=6",)
        assert _meta(a)["condition"]["capacity"] == 6

    def test_rides_along_with_the_map(self):
        """맵 세트와 적재량은 서로 지우지 않는다 — 순서는 map-dir 먼저."""
        a = _args("--map-dir", os.path.join(SYNTH, "r11p6l21"), "--robots", "20",
                  "--capacity", "6")
        assert a.extra_args == (f"--map-dir={a.map_dir}", "--capacity=6")
        cond = _meta(a)["condition"]
        assert (cond["map_dir"], cond["capacity"]) == ("map/synth/r11p6l21", 6)

    @pytest.mark.parametrize("bad", ["0", "7", "-1"])
    def test_out_of_contract_range_is_rejected(self, bad):
        """시뮬이 맞기 전에 여기서 죽어야 한다 — 탐색은 시작하면 몇십 분이다."""
        with pytest.raises(SystemExit):
            _args("--capacity", bad)


class TestArrivalLoad:
    """부하를 초로 받아 틱으로 환산한다 (-194). 틱 길이는 시뮬 상수에서 읽는다."""

    def test_tick_length_matches_the_sim(self, monkeypatch):
        """여기서 숫자를 또 적으면 틱 모델이 바뀔 때 워커만 옛 값을 쓴다.

        sys.path 는 monkeypatch 로 건드린다 — 직접 insert 하면 이 테스트가 끝난 뒤에도
        경로가 남아 다른 테스트가 다른 모듈을 집을 수 있다 (teardown 에서 복원된다).
        """
        monkeypatch.syspath_prepend(SIM_ENGINE)
        from map_loader import CELL_M
        from pibt_core import MOVE_TICKS
        assert rs.tick_seconds(1.0, SIM_ENGINE) == pytest.approx(CELL_M / (1.0 * MOVE_TICKS))
        assert rs.tick_seconds(0.5, SIM_ENGINE) == pytest.approx(CELL_M / (0.5 * MOVE_TICKS))

    def test_seconds_become_ticks(self):
        a = _args("--arrival-s", "4")
        assert a.order_gap == pytest.approx(4 / a.dt)
        assert (a.arrival_s, a.orders_per_h) == pytest.approx((4.0, 900.0))

    def test_speed_does_not_change_the_real_load(self):
        """속도를 바꿔도 초 간격은 그대로여야 한다 — 틱 수만 달라진다."""
        slow, fast = _args("--arrival-s", "4", "--speed", "0.518"), _args("--arrival-s", "4")
        assert slow.arrival_s == pytest.approx(fast.arrival_s)
        assert slow.orders_per_h == pytest.approx(fast.orders_per_h)
        # 느릴수록 틱 하나가 길어지니 같은 초를 **더 적은** 틱으로 센다.
        assert slow.dt > fast.dt
        assert slow.order_gap < fast.order_gap
        assert slow.order_gap * slow.dt == pytest.approx(fast.order_gap * fast.dt)

    def test_raw_order_gap_still_works_and_reports_its_real_load(self):
        """구 study 재현용 원시 통로. 넘긴 틱은 그대로 가고 실시간 부하는 역산해 기록한다."""
        a = _args("--order-gap", "15")
        assert a.order_gap == pytest.approx(15.0)
        assert a.arrival_s == pytest.approx(15.0 * a.dt)

    def test_speed_reaches_the_sim_only_when_not_default(self):
        assert _args().extra_args == ()
        assert _args("--speed", "0.518").extra_args == ("--speed=0.518",)

    def test_meta_records_the_load_unambiguously(self):
        """틱 값만 남기면 틱 길이를 모르는 사람이 부하를 못 읽는다."""
        cond = _meta(_args("--arrival-s", "4", "--speed", "0.518"))["condition"]
        assert cond["orders_per_h"] == pytest.approx(900.0)
        assert cond["arrival_s"] == pytest.approx(4.0)
        assert cond["speed"] == 0.518
        assert cond["dt_s"] == pytest.approx(_args("--speed", "0.518").dt, abs=1e-5)

    @pytest.mark.parametrize("bad", [["--speed", "0"], ["--speed", "9"], ["--arrival-s", "0"]])
    def test_out_of_range_is_rejected(self, bad):
        with pytest.raises(SystemExit):
            _args(*bad)


class TestRelativeTo:
    def test_inside_root_becomes_relative_with_slashes(self):
        assert rs._relative_to(os.path.join(FMS_ROOT, "map", "synth", "x"), FMS_ROOT) == "map/synth/x"

    def test_outside_root_stays_absolute(self):
        outside = os.path.abspath(os.path.join(FMS_ROOT, "..", "elsewhere"))
        assert rs._relative_to(outside, FMS_ROOT) == outside


def _meta(args, tmp=None):
    """dump_best 가 쓰는 meta 를 실제 함수로 만들어 본다 (study 는 최소 스텁)."""
    import tempfile
    args.pinned = {}
    args.out = tmp or tempfile.mkdtemp(prefix="run_study_meta_")
    study = SimpleNamespace(
        best_value=1.0, trials=[0],
        best_trial=SimpleNamespace(params={"wait_cost": 2.0}, number=0, user_attrs={}))
    rs.dump_best(study, args, "v2", ["wait_cost"])
    with open(os.path.join(args.out, f"meta_{args.study}.json"), encoding="utf-8") as f:
        return json.load(f)
