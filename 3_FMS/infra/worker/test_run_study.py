# -*- coding: utf-8 -*-
"""θ 탐색 워커의 맵 세트 연결 검사 (S15P21A106-183).

시뮬·Optuna storage 없이 인자 파싱과 meta 조립만 본다.
`3_FMS/infra/worker` 에서 `python -m pytest -q`.

못 박는 것 두 가지.

1. **공식 맵 경로는 안 변한다** — `--map-dir` 을 안 주면 시뮬에 넘기는 인자가 비어 있고
   meta 에 `map_dir` 키가 안 붙는다. 기존 study 재실행이 같은 θ 를 낸다.
2. **합성 창고는 그 맵의 충전 존이 상한이다** — wallA 상수 28 을 쓰면, 존이 24 인 창고에
   26 대를 걸어 두고 컨테이너가 다 뜬 뒤에야 시뮬 assert 로 죽는다.
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
    @pytest.mark.parametrize("name,fleet,capacity", SYNTH_CASES)
    def test_extra_args_carry_the_map(self, name, fleet, capacity):
        a = _args("--map-dir", os.path.join(SYNTH, name), "--robots", str(fleet))
        assert a.extra_args == (f"--map-dir={a.map_dir}",)
        assert os.path.isabs(a.map_dir)

    @pytest.mark.parametrize("name,fleet,capacity", SYNTH_CASES)
    def test_capacity_comes_from_that_map(self, name, fleet, capacity):
        """상한은 wallA 상수가 아니라 그 창고의 충전 존이다."""
        assert rs.charge_zone_capacity(os.path.join(SYNTH, name), SIM_ENGINE) == capacity
        _args("--map-dir", os.path.join(SYNTH, name), "--robots", str(capacity))
        with pytest.raises(SystemExit):
            _args("--map-dir", os.path.join(SYNTH, name), "--robots", str(capacity + 1))

    def test_meta_records_a_portable_path(self):
        """절대 경로를 박으면 다른 머신·컨테이너에서 호출을 복원할 수 없다."""
        a = _args("--map-dir", os.path.join(SYNTH, "r11p6l21"), "--robots", "20")
        assert a.map_ref == "map/synth/r11p6l21"
        assert _meta(a)["condition"]["map_dir"] == "map/synth/r11p6l21"

    def test_missing_folder_is_rejected_before_the_study(self):
        with pytest.raises(SystemExit):
            _args("--map-dir", os.path.join(SYNTH, "없는창고"))


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
