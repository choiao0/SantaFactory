package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SimulationDtoJsonTest {

    private final ObjectMapper om = new ObjectMapper();

    @Test
    void request_snake_case_roundtrip() throws Exception {
        String json = """
                {
                  "run_id": "est_77_n3",
                  "seed": 42,
                  "warehouse": {
                    "worker_count": 4,
                    "inbound_start": "01:00", "inbound_end": "09:00",
                    "outbound_start": "13:00", "outbound_end": "18:00",
                    "inbound_avg": 480, "outbound_avg": 500
                  },
                  "amr": {
                    "count": 3, "speed_empty": 1.2, "speed_loaded": 1.0,
                    "consumption": 0.02, "battery": 100.0, "charge_time": 3600,
                    "charge_threshold": 0.2, "capacity": 8
                  },
                  "inbound": [
                    { "inbound_id": 5001, "arrived_at_s": 3,
                      "lines": [ { "product_id": 7, "rack_id": "A2", "qty": 20 } ] }
                  ],
                  "outbound": [
                    { "order_id": 1001, "ordered_at_s": 0,
                      "lines": [ { "product_id": 7, "rack_id": "A2", "qty": 1 },
                                 { "product_id": 11, "rack_id": "A9", "qty": 3 } ] }
                  ]
                }
                """;

        SimulationRequest req = om.readValue(json, SimulationRequest.class);

        assertThat(req.runId()).isEqualTo("est_77_n3");
        assertThat(req.warehouse().workerCount()).isEqualTo(4);
        assertThat(req.amr().chargeThreshold()).isEqualTo(0.2);
        assertThat(req.inbound().get(0).arrivedAtS()).isEqualTo(3L);
        assertThat(req.outbound().get(0).lines()).hasSize(2);

        JsonNode out = om.readTree(om.writeValueAsString(req));
        assertThat(out.get("run_id").asText()).isEqualTo("est_77_n3");
        assertThat(out.get("warehouse").get("inbound_avg").asInt()).isEqualTo(480);
        assertThat(out.get("amr").get("speed_empty").asDouble()).isEqualTo(1.2);
        assertThat(out.get("outbound").get(0).get("ordered_at_s").asLong()).isZero();
        assertThat(out.get("outbound").get(0).get("lines").get(0).get("rack_id").asText()).isEqualTo("A2");
    }

    @Test
    void response_snake_case_deserialize() throws Exception {
        String json = """
                {
                  "run_id": "est_77_n3",
                  "status": "done",
                  "error": null,
                  "kpi": {
                    "orders_total": 50, "orders_completed": 50,
                    "inbound_total": 48, "inbound_completed": 48,
                    "makespan_s": 1740, "lead_time_mean_s": 210.5,
                    "lead_time_p90_s": 402.0, "queue_time_mean_s": 87.3,
                    "throughput_orders_per_h": 96.4, "throughput_tasks_per_h": 182.0,
                    "amr_utilization": 0.63, "conflict_wait_ratio": 0.004,
                    "distance_total_m": 12480, "charge_downtime_s": 0
                  }
                }
                """;

        SimulationResponse res = om.readValue(json, SimulationResponse.class);

        assertThat(res.status()).isEqualTo("done");
        assertThat(res.error()).isNull();
        assertThat(res.kpi().makespanS()).isEqualTo(1740L);
        assertThat(res.kpi().leadTimeP90S()).isEqualTo(402.0);
        assertThat(res.kpi().throughputOrdersPerH()).isEqualTo(96.4);
        assertThat(res.kpi().chargeDowntimeS()).isZero();

        JsonNode out = om.readTree(om.writeValueAsString(res));
        assertThat(out.get("kpi").get("lead_time_p90_s").asDouble()).isEqualTo(402.0);
        assertThat(out.get("kpi").get("throughput_orders_per_h").asDouble()).isEqualTo(96.4);
    }

    @Test
    void verify_request_scenario_snake_case_roundtrip() throws Exception {
        VerifyRequest req = new VerifyRequest("verify_77", 4, 600L, "est_77_n4", 77L, 101L,
                VerifyRequest.Scenario.ofOrders(101L, new VerifyRequest.Orders(null, java.util.List.of(
                        new SimulationRequest.Outbound(1L, 23659L, java.util.List.of(
                                new SimulationRequest.Line(3L, "A3", 2)))))));

        JsonNode out = om.readTree(om.writeValueAsString(req));
        assertThat(out.get("run_id").asText()).isEqualTo("verify_77");
        assertThat(out.get("scenario").get("seed").asLong()).isEqualTo(101L);
        JsonNode order = out.get("scenario").get("orders").get("outbound").get(0);
        assertThat(order.get("ordered_at_s").asLong()).isEqualTo(23659L);
        assertThat(order.get("lines").get(0).get("rack_id").asText()).isEqualTo("A3");

        VerifyRequest roundTripped = om.readValue(om.writeValueAsString(req), VerifyRequest.class);
        assertThat(roundTripped).isEqualTo(req);
    }

    /** 계약 §3 예시 그대로 — 안 읽는 키(runner, rtf_mean, counters …)가 섞여 있어도 깨지지 않아야 한다. */
    @Test
    void verify_result_reads_verify_and_kpi_blocks_and_ignores_unknown_fields() throws Exception {
        String json = """
                {
                  "run_id": "verify_77", "status": "done", "error": null,
                  "verify": {
                    "runner": "sim-runner-gpu01",
                    "n_robots": 14, "robots_online": 13,
                    "window_s": 600, "elapsed_s": 600.4,
                    "started_at": "2026-09-09T02:10:00.000Z", "ended_at": "2026-09-09T02:20:00.400Z",
                    "rtf_mean": 1.02, "ram_mb_max": 5120, "vram_mb_max": 9800, "isaac_instances": 1,
                    "scenario_sha256": "abc", "scenario_ack": true,
                    "reason": "window elapsed",
                    "fms": { "node": "fms-core", "ticks": 118, "status": "done", "error": null, "planner": "kernel",
                             "counters": {"open_tasks": 3, "done_tasks": 11, "orders_done": 9, "orders_total": 12},
                             "warnings": ["theta file missing"] }
                  },
                  "kpi": { "orders_total": 12, "orders_completed": 9, "inbound_total": 0, "inbound_completed": 0,
                           "makespan_s": 118, "lead_time_mean_s": 61.2, "lead_time_p90_s": 90.0, "queue_time_mean_s": 3.1,
                           "throughput_orders_per_h": 274.6, "throughput_tasks_per_h": 335.6, "amr_utilization": 0.71,
                           "conflict_wait_ratio": 0.02, "distance_total_m": 140, "charge_downtime_s": 0 },
                  "artifacts": { "video": "verify_77/demo.mp4" },
                  "source_run_id": "est_77_n14", "estimate_id": 77
                }
                """;

        VerifyResultResponse res = om.readValue(json, VerifyResultResponse.class);

        assertThat(res.estimateId()).isEqualTo(77L);
        assertThat(res.sourceRunId()).isEqualTo("est_77_n14");
        assertThat(res.artifacts().video()).isEqualTo("verify_77/demo.mp4");
        assertThat(res.verify().nRobots()).isEqualTo(14);
        assertThat(res.verify().robotsOnline()).isEqualTo(13);
        assertThat(res.verify().windowS()).isEqualTo(600);
        assertThat(res.verify().reason()).isEqualTo("window elapsed");
        assertThat(res.verify().fms().warnings().get(0).asText()).isEqualTo("theta file missing");
        assertThat(res.kpi().throughputOrdersPerH()).isEqualTo(274.6);
        assertThat(res.kpi().leadTimeP90S()).isEqualTo(90.0);
        assertThat(res.kpi().conflictWaitRatio()).isEqualTo(0.02);
    }

    @Test
    void verify_result_without_verify_and_kpi_still_deserializes() throws Exception {
        VerifyResultResponse res = om.readValue(
                """
                {"run_id":"verify_77","status":"failed","error":"start timeout","estimate_id":77,"artifacts":null}
                """, VerifyResultResponse.class);

        assertThat(res.status()).isEqualTo("failed");
        assertThat(res.verify()).isNull();
        assertThat(res.kpi()).isNull();
    }

    // ── DES 피크 구간 · 물리 지표 (명세 §A·§C, S15P21A106-244) ─────────────────

    /** 명세 §A 예시 그대로 — 구간이 있으면 gz_b64 까지 온다. */
    @Test
    void sim_result_reads_verify_slice_with_trajectory() throws Exception {
        String json = """
                {
                  "run_id": "est_18_n10", "status": "done", "error": null,
                  "verify_slice": {
                    "format": 1, "source": "est_18_n10",
                    "t0_s": 4420.0, "t_start_s": 4360.0, "t_end_s": 5080.0, "warmup_s": 60.0, "window_s": 600.0,
                    "n_robots": 10, "tasks_done": 162, "moves": 2970, "turns": 191, "reverses": 205,
                    "b64_bytes": 303104, "gz_b64": "H4sIAAAA..."
                  }
                }
                """;

        SimulationResponse res = om.readValue(json, SimulationResponse.class);

        assertThat(res.verifySlice()).isNotNull();
        assertThat(res.verifySlice().hasTrajectory()).isTrue();
        assertThat(res.verifySlice().tasksDone()).isEqualTo(162);
        assertThat(res.verifySlice().gzB64()).isEqualTo("H4sIAAAA...");
        // meta() 는 gz_b64 를 뺀 나머지만 — DB meta_json 저장에 이 모양을 쓴다
        assertThat(om.writeValueAsString(res.verifySlice().meta())).doesNotContain("gz_b64");
    }

    /** 구간을 못 만들었으면 gz_b64 없이 error 만 온다 — 그래도 화면이 사유를 보일 수 있게 저장한다. */
    @Test
    void sim_result_reads_verify_slice_without_trajectory() throws Exception {
        String json = """
                {"run_id": "est_18_n15", "status": "done",
                 "verify_slice": {"format": 1, "source": "est_18_n15", "error": "slice too large: 820000 bytes"}}
                """;

        SimulationResponse res = om.readValue(json, SimulationResponse.class);

        assertThat(res.verifySlice().hasTrajectory()).isFalse();
        assertThat(res.verifySlice().error()).isEqualTo("slice too large: 820000 bytes");
    }

    /** {@code scenario.slice} + {@code trajectory_gz_b64} 조합(궤적 있음) — orders 는 싣지 않는다. */
    @Test
    void verify_request_trajectory_scenario_roundtrip() throws Exception {
        VerifyRequest.Slice slice = new VerifyRequest.Slice(4420.0, 60.0, 600.0, 162);
        VerifyRequest req = new VerifyRequest("verify_18_n10_1", 10, 600L, "est_18_n10", 18L, 101L,
                VerifyRequest.Scenario.ofTrajectory(101L, "H4sIAAAA...", slice));

        JsonNode out = om.readTree(om.writeValueAsString(req));
        assertThat(out.get("scenario").get("trajectory_gz_b64").asText()).isEqualTo("H4sIAAAA...");
        assertThat(out.get("scenario").get("slice").get("tasks_done").asInt()).isEqualTo(162);
        assertThat(out.get("scenario").get("orders").isNull()).isTrue();

        VerifyRequest roundTripped = om.readValue(om.writeValueAsString(req), VerifyRequest.class);
        assertThat(roundTripped).isEqualTo(req);
    }

    /** 명세 §C 예시 — 구간 재생 창의 지연·창 동작 비율·접촉 지표를 판정에 쓸 수 있게 읽는다. */
    @Test
    void verify_result_reads_physics_block() throws Exception {
        String json = """
                {
                  "run_id": "verify_18_n10_1", "status": "done", "error": null, "estimate_id": 18,
                  "physics": {
                    "engine": "isaac-headless", "n_robots": 10,
                    "sim_s": 660.0, "window_sim_s": 600.0, "warmup_s": 60.0, "window_s": 600.0, "wall_s": 701.3, "rtf": 0.94,
                    "robot_contacts": 0, "robot_min_gap_m": 0.334, "rack_contacts": 0, "rack_worst_pen_mm": 0.0,
                    "zone_intrusions": 284, "zone_worst_pen_mm": 46.6,
                    "stall_steps": 0, "turn_gaveup": 1, "recover_events": 0, "cell_overlaps": 62,
                    "actions_started": 3140, "actions_completed": 3134,
                    "lag": {"n": 2804, "p50_s": 40.4, "p90_s": 91.9, "max_s": 157.6, "mean_s": 47.0, "late_ratio": 0.9},
                    "window_actions": {"planned": 3365, "started": 2804, "ratio": 0.833, "overdue_s": 157.0},
                    "blocked": {"robot_frames": 372000, "obstacle": 0, "release": 10406, "adg_self": 0, "adg_other": 89963, "ratio": 0.27},
                    "des_window": {"tasks_done": 162, "moves": 2970, "turns": 191, "reverses": 205},
                    "runner": "sim-runner-gpu01"
                  }
                }
                """;

        VerifyResultResponse res = om.readValue(json, VerifyResultResponse.class);

        assertThat(res.physics()).isNotNull();
        assertThat(res.physics().robotContacts()).isZero();
        assertThat(res.physics().robotMinGapM()).isEqualTo(0.334);
        assertThat(res.physics().windowActions().ratio()).isEqualTo(0.833);
        assertThat(res.physics().lag().p50S()).isEqualTo(40.4);
        assertThat(res.physics().desWindow().tasksDone()).isEqualTo(162);
    }
}
