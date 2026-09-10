"""fms_core.scenario — Start 파싱 · sha 대조 · scenario → 주문/스트림 옵션."""
import json

import pytest

from fms_core import scenario as S


def start(**over):
    d = {"run_id": "v1", "n_robots": 2, "timeout_s": 300}
    d.update(over)
    return json.dumps(d)


class TestRunSpec:
    def test_defaults_serials_and_manufacturer(self):
        spec = S.RunSpec.from_json(start())
        assert [r.serial for r in spec.robots] == ["amr01", "amr02"]
        assert spec.robots[0].manufacturer == "idealworks" and spec.robots[0].model == "iw_hub"
        assert spec.scenario == {} and spec.scenario_sha256 is None and spec.timeout_s == 300

    def test_models_override(self):
        spec = S.RunSpec.from_json(start(models=[{"serial": "r1", "manufacturer": "acme"}, {"serial": "r2"}]))
        assert spec.robots[0] == S.Robot("r1", "acme", "iw_hub") and spec.robots[1].serial == "r2"

    @pytest.mark.parametrize("over,msg", [
        ({"run_id": "bad id"}, "run_id"), ({"n_robots": 0}, "n_robots"), ({"n_robots": True}, "n_robots"),
        ({"timeout_s": -1}, "timeout_s"), ({"models": [{"serial": "x"}]}, "models"),
        ({"models": [{"serial": "a"}, {"serial": "a"}]}, "unique"), ({"scenario": [1]}, "scenario"),
        ({"scenario": {"a": 1}, "scenario_sha256": "0" * 64}, "mismatch")])
    def test_rejects(self, over, msg):
        with pytest.raises(ValueError, match=msg):
            S.RunSpec.from_json(start(**over))

    def test_not_json(self):
        with pytest.raises(ValueError, match="JSON"):
            S.RunSpec.from_json("{nope")
        with pytest.raises(ValueError, match="object"):
            S.RunSpec.from_json("[1]")

    def test_sha_matches_host_orch_rule(self):
        sc = {"seed": 42, "orders": {"outbound": [{"order_id": 1, "ordered_at_s": 3, "lines": [{"rack_id": "A3", "qty": 2}]}]}}
        spec = S.RunSpec.from_json(start(scenario=sc, scenario_sha256=S.scenario_sha256(sc)))
        assert spec.scenario_sha256 == S.scenario_sha256(sc)
        assert S.canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'


class TestScenarioOrders:
    def test_generator_output_and_offset(self):
        sc = {"window_start_s": 10, "orders": {"meta": {"seed": 42}, "outbound": [
            {"order_id": 7, "ordered_at_s": 8, "lines": [{"rack_id": "A1"}]},
            {"order_id": 8, "ordered_at_s": 25, "store_id": 1, "lines": [{"rack_id": "A2", "qty": 3}, {"rack_id": "B1"}]}]}}
        assert S.scenario_orders(sc) == [{"ordered_at_s": 15, "lines": [{"rack_id": "A2", "qty": 3}, {"rack_id": "B1", "qty": 1}],
                                         "order_id": 8}]

    def test_bare_list_and_empty(self):
        assert S.scenario_orders({}) == []
        assert S.scenario_orders({"orders": [{"ordered_at_s": 0, "lines": []}]}) == [{"ordered_at_s": 0, "lines": [], "order_id": 0}]

    @pytest.mark.parametrize("sc", [{"orders": 5}, {"orders": [{"lines": []}]}, {"orders": [{"ordered_at_s": 1, "lines": [{}]}]},
                                    {"orders": [{"ordered_at_s": 1, "lines": [{"rack_id": "A1", "qty": 0}]}]},
                                    {"orders": [], "window_start_s": -1}])
    def test_rejects(self, sc):
        with pytest.raises(ValueError):
            S.scenario_orders(sc)


def test_max_totes_matches_the_kernel():
    """적재 상한(1~6)은 커널 상수의 사본이다 — 어긋나면 커널이 받는 요청을 fms-core 가 먼저 거절한다.
    sim_engine 만 있으면 도는 자리에 둔다(견적 패리티 테스트는 matplotlib 이 없으면 통째로 skip 된다)."""
    from fms_core.kernel_planner import ensure_sim_engine
    ensure_sim_engine()
    from kernel.core import MAX_TOTES_PER_TRIP as KERNEL_MAX
    assert S.MAX_TOTES_PER_TRIP == KERNEL_MAX


class TestStreamOptions:
    def test_defaults_match_the_estimate_worker(self):
        """필드가 없으면 견적 워커와 같은 기본값 — 왕복당 1토트, 토트당 8개, 토트당 서비스 5틱 (계약 v2.6)."""
        assert S.stream_options({}) == {"seed": 42, "capacity": 1, "tote_units": 8, "svc_per_tote": 5,
                                        "order_gap": 50.0, "inbound_gap": None, "shifts": ("out",)}

    def test_des_passthrough(self):
        o = S.stream_options({"seed": 7, "amr": {"capacity": 3, "tote_units": 12},
                              "inbound_gap_s": 48.0, "shifts": "in,in,out"})
        assert o == {"seed": 7, "capacity": 3, "tote_units": 12, "svc_per_tote": 5,
                     "order_gap": 50.0, "inbound_gap": 48.0, "shifts": ("in", "in", "out")}

    def test_outbound_gap_passthrough(self):
        """입고 창의 간격 기본값이 여기서 온다 (sim_v2 --order-gap, 1초 = 1틱)."""
        assert S.stream_options({"outbound_gap_s": 30.0})["order_gap"] == 30.0

    def test_null_amr_fields_fall_back(self):
        """백엔드는 채우지 않은 amr 필드를 null 로 보낸다 (estimate_worker._orders_flags 와 같은 처리)."""
        o = S.stream_options({"amr": {"capacity": None, "tote_units": None}})
        assert o["capacity"] == 1 and o["tote_units"] == 8

    @pytest.mark.parametrize("sc", [{"seed": "x"}, {"capacity": 0}, {"capacity": 7}, {"capacity": True},
                                    {"amr": {"tote_units": 0}}, {"inbound_gap_s": 0}, {"outbound_gap_s": 0},
                                    {"inbound_gap_s": 5, "shifts": "in,x"}])
    def test_rejects(self, sc):
        with pytest.raises(ValueError):
            S.stream_options(sc)
