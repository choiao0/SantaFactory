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
                new VerifyRequest.Scenario(101L, new VerifyRequest.Orders(null, java.util.List.of(
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
}
