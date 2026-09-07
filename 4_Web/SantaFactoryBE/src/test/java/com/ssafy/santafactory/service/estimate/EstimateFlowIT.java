package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.client.SimulationClient;
import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.repository.SimScenarioRepository;
import com.ssafy.santafactory.support.PostgresSupport;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 견적 생성 → 결과 수신 → 판정 확정까지 실제 Postgres 로 한 번 관통한다.
 *
 * <p>단위 테스트가 조각별로 검증한 것들(비용·판정·상태 전이)이 <b>실제 스키마와 리포지토리 위에서도
 * 이어지는지</b> 보는 테스트다. 큐 발행만 막고(SimulationClient) 나머지는 전부 진짜다 —
 * 트랜잭션도 실제로 커밋되므로 UNIQUE·FK 제약이 살아 있는 상태에서 확인된다.
 */
@SpringBootTest
class EstimateFlowIT extends PostgresSupport {

    /** 큐만 막는다. 발행 로직(runId 생성·대수별 메시지)은 그대로 돈다. */
    @MockBean
    SimulationClient simulationClient;

    @Autowired
    EstimateService estimateService;
    @Autowired
    EstimateRepository estimateRepository;
    @Autowired
    SimScenarioRepository scenarioRepository;
    @Autowired
    JdbcTemplate jdbc;

    private Long warehouseId;

    @BeforeEach
    void seedWarehouse() {
        scenarioRepository.deleteAllInBatch();
        estimateRepository.deleteAllInBatch();
        jdbc.update("DELETE FROM warehouses");
        // 창고 시드(품고)와 같은 값 — 목표 처리율 95 %, 가동률 80 %, 예산 3억
        warehouseId = jdbc.queryForObject("""
                INSERT INTO warehouses
                    (name, area, width, length, worker_count,
                     inbound_start, inbound_end, outbound_start, outbound_end, status,
                     inbound_avg, outbound_avg, outbound_rate,
                     target_throughput, target_utilization, budget_limit)
                VALUES ('품고', 9900.0, 110.0, 90.0, 12,
                        '2026-01-01 01:00:00', '2026-01-01 09:00:00',
                        '2026-01-01 13:00:00', '2026-01-01 18:00:00', 'OUTBOUND',
                        600, 800, 95.0, 95.0, 80.0, 300000000)
                RETURNING warehouse_id
                """, Long.class);
    }

    @Test
    void runs_the_whole_sweep_and_lands_on_a_recommendation() {
        EstimateCreateResponse created = estimateService.create(
                new EstimateCreateRequest(warehouseId, null, null, null, null));

        // 예산 3억이면 19대까지 살 수 있지만 상한 8이 먼저 걸린다
        assertThat(created.maxAmrCount()).isEqualTo(8);
        List<SimScenario> queued = scenarioRepository.findByEstimateIdOrderByAmrCountAsc(created.estimateId());
        assertThat(queued).hasSize(8);
        assertThat(queued).extracting(SimScenario::getStatus).containsOnly(RunStatus.QUEUED);
        assertThat(queued).extracting(SimScenario::getRunId)
                .containsExactly("est_%d_n1".formatted(created.estimateId()),
                        "est_%d_n2".formatted(created.estimateId()),
                        "est_%d_n3".formatted(created.estimateId()),
                        "est_%d_n4".formatted(created.estimateId()),
                        "est_%d_n5".formatted(created.estimateId()),
                        "est_%d_n6".formatted(created.estimateId()),
                        "est_%d_n7".formatted(created.estimateId()),
                        "est_%d_n8".formatted(created.estimateId()));

        // 대수를 늘릴수록 처리율은 오르고 가동률은 떨어지는 곡선을 하나씩 되돌려준다
        for (int amrCount = 1; amrCount <= 8; amrCount++) {
            estimateService.applyResult(done(created.estimateId(), amrCount));
        }

        EstimateDetailResponse detail = estimateService.detail(created.estimateId());
        assertThat(detail.status()).isEqualTo(EstimateStatus.DONE);
        assertThat(detail.recommendedCount()).isEqualTo(8);   // 96 % ≥ 95 %, 84 % ≥ 80 %
        assertThat(detail.reasonCode()).isNull();
        assertThat(detail.elapsedSeconds()).isNotNull();
        assertThat(detail.runs()).hasSize(8);
        assertThat(detail.runs()).extracting(EstimateDetailResponse.Run::status).containsOnly(RunStatus.DONE);
        assertThat(detail.runs().get(7).throughput()).isEqualTo(96.0);
    }

    @Test
    void one_failed_run_does_not_stop_the_rest() {
        EstimateCreateResponse created = estimateService.create(
                new EstimateCreateRequest(warehouseId, null, null, null, null));

        for (int amrCount = 1; amrCount <= 7; amrCount++) {
            estimateService.applyResult(done(created.estimateId(), amrCount));
        }
        estimateService.applyResult(new SimulationResponse(
                "est_%d_n8".formatted(created.estimateId()), "failed", "시뮬 정체 감지", null));

        EstimateDetailResponse detail = estimateService.detail(created.estimateId());
        assertThat(detail.status()).isEqualTo(EstimateStatus.PARTIAL);
        // 8대가 빠지면 목표 처리율 95 % 에 닿는 대수가 없다 (7대는 84 %)
        assertThat(detail.recommendedCount()).isNull();
        assertThat(detail.reasonCode()).isEqualTo(ReasonCode.THROUGHPUT_SHORT);
        assertThat(detail.runs().get(7).status()).isEqualTo(RunStatus.FAILED);
        assertThat(detail.runs().get(7).error()).isEqualTo("시뮬 정체 감지");
    }

    @Test
    void a_redelivered_result_does_not_overwrite_the_first_one() {
        EstimateCreateResponse created = estimateService.create(
                new EstimateCreateRequest(warehouseId, null, null, null, null));
        String runId = "est_%d_n3".formatted(created.estimateId());

        estimateService.applyResult(done(created.estimateId(), 3));
        estimateService.applyResult(new SimulationResponse(runId, "done", null,
                new SimulationResponse.Kpi(100, 1, null, null, null, null, null, null,
                        null, null, 0.01, null, null, null)));

        SimScenario run = scenarioRepository.findByRunId(runId).orElseThrow();
        assertThat(run.getThroughput()).isEqualTo(36.0);   // 3대 첫 결과가 유지된다
        assertThat(run.getStatus()).isEqualTo(RunStatus.DONE);
    }

    @Test
    void a_stuck_run_is_recovered_by_the_timeout_sweep() {
        EstimateCreateResponse created = estimateService.create(
                new EstimateCreateRequest(warehouseId, null, null, null, null));
        for (int amrCount = 1; amrCount <= 7; amrCount++) {
            estimateService.applyResult(done(created.estimateId(), amrCount));
        }
        // 8대 run 만 결과가 오지 않은 상태로 발행 시각을 과거로 돌린다
        jdbc.update("UPDATE simscenarios SET published_at = published_at - INTERVAL '2 hours' WHERE status = 'QUEUED'");

        assertThat(estimateService.sweepTimeouts()).isEqualTo(1);

        EstimateDetailResponse detail = estimateService.detail(created.estimateId());
        assertThat(detail.runs().get(7).status()).isEqualTo(RunStatus.TIMEOUT);
        assertThat(detail.status()).isEqualTo(EstimateStatus.PARTIAL);
        assertThat(detail.reasonCode()).isEqualTo(ReasonCode.THROUGHPUT_SHORT);
    }

    /** 대수가 늘면 처리율 +12 %p, 가동률 −2 %p. 8대에서 96 % / 84 % 로 목표(95/80)를 처음 넘는다. */
    private SimulationResponse done(long estimateId, int amrCount) {
        SimulationResponse.Kpi kpi = new SimulationResponse.Kpi(
                100, amrCount * 12, null, null,
                null, null, null, null,
                null, null,
                (100 - amrCount * 2) / 100.0, null, null, null);
        return new SimulationResponse("est_%d_n%d".formatted(estimateId, amrCount), "done", null, kpi);
    }
}
