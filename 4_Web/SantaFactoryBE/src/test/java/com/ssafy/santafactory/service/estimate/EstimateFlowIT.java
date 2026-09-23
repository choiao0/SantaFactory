package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.client.SimulationClient;
import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.dto.simulation.VerifyResultResponse;
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

import static com.ssafy.santafactory.support.TestPrincipals.ADMIN;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

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

    /** 예산 3억 ÷ 대당 1,550만 = 19대 + 여유 1. 충전 존 상한 28 보다 작아 예산이 실질 상한이다. */
    private static final int MAX_AMR = 20;

    private Long warehouseId;

    @BeforeEach
    void seedWarehouse() {
        scenarioRepository.deleteAllInBatch();
        estimateRepository.deleteAllInBatch();
        // 자식부터: products → rack/stores → zones → facility/warehouses (FK 순서)
        jdbc.update("DELETE FROM products");
        jdbc.update("DELETE FROM rack");
        jdbc.update("DELETE FROM stores");
        jdbc.update("DELETE FROM zones");
        jdbc.update("DELETE FROM facility");
        jdbc.update("DELETE FROM warehouses");
        // 창고 시드(품고)와 같은 값 — 하루 출고 6,000건, 목표 처리율 95 %, 가동률 80 %, 예산 3억.
        // 출고 물량은 팀 결정(2026-09-11) 견적 부하 "하루 6,000건 / 6시간" 이다 (S15P21A106-97)
        warehouseId = jdbc.queryForObject("""
                INSERT INTO warehouses
                    (name, area, width, length, worker_count,
                     inbound_start, inbound_end, outbound_start, outbound_end, status,
                     inbound_avg, outbound_avg, outbound_rate,
                     target_throughput, target_utilization, budget_limit)
                VALUES ('품고', 9900.0, 110.0, 90.0, 12,
                        '2026-01-01 01:00:00', '2026-01-01 09:00:00',
                        '2026-01-01 13:00:00', '2026-01-01 18:00:00', 'OUTBOUND',
                        600, 6000, 95.0, 95.0, 80.0, 300000000)
                RETURNING warehouse_id
                """, Long.class);
        seedProductMaster(warehouseId);
    }

    /**
     * {@code OutboundOrderGenerator}가 출고 주문을 뽑아낼 최소한의 상품 마스터.
     * 실제 견적 흐름(주문 생성 → DES 발행)이 상품·랙 데이터 없이는 못 돈다.
     */
    private void seedProductMaster(long warehouseId) {
        Long facilityId = jdbc.queryForObject(
                "INSERT INTO facility (type, x, y) VALUES ('SHELF', 0, 0) RETURNING facility_id", Long.class);
        Long zoneId = jdbc.queryForObject(
                "INSERT INTO zones (warehouse_id, facility_id, zone_code, rack_count) VALUES (?, ?, 'Z1', 2) "
                        + "RETURNING zone_id",
                Long.class, warehouseId, facilityId);
        Long rackId = jdbc.queryForObject(
                "INSERT INTO rack (zone_id, field) VALUES (?, 'A1') RETURNING rack_id", Long.class, zoneId);
        Long storeId = jdbc.queryForObject(
                "INSERT INTO stores (zone_id, name, category, outbound_count) VALUES (?, 'DemoStore', 'shoes', 500) "
                        + "RETURNING store_id",
                Long.class, zoneId);
        for (int i = 0; i < 20; i++) {
            jdbc.update("INSERT INTO products (store_id, rack_id, name, price, count, count_init) "
                    + "VALUES (?, ?, ?, 10000, 100, 100)", storeId, rackId, "item" + i);
        }
    }

    @Test
    void runs_the_whole_sweep_and_lands_on_a_recommendation() {
        EstimateCreateResponse created = estimateService.create(
new EstimateCreateRequest(warehouseId, null, null, null, null, null, null), ADMIN);

        // 예산 3억 ÷ 대당 1,550만 = 19대 + 여유 1 = 20대. 충전 존 상한 28 보다 작아 예산이 먼저 걸린다
        assertThat(created.maxAmrCount()).isEqualTo(MAX_AMR);
        List<SimScenario> queued = scenarioRepository.findByEstimateIdOrderByAmrCountAsc(created.estimateId());
        assertThat(queued).hasSize(MAX_AMR);
        assertThat(queued).extracting(SimScenario::getStatus).containsOnly(RunStatus.QUEUED);
        assertThat(queued).extracting(SimScenario::getRunId)
                .startsWith("est_%d_n1".formatted(created.estimateId()))
                .endsWith("est_%d_n%d".formatted(created.estimateId(), MAX_AMR));
        // 발행은 커밋 뒤 이벤트 리스너가 한다 — 실제 트랜잭션 매니저 위에서 대수만큼 나갔는지 본다
        verify(simulationClient, times(MAX_AMR)).publish(any());

        // 대수를 늘릴수록 처리율은 오르고 가동률은 떨어지는 곡선을 하나씩 되돌려준다
        for (int amrCount = 1; amrCount <= MAX_AMR; amrCount++) {
            estimateService.applyResult(done(created.estimateId(), amrCount));
        }

        EstimateDetailResponse detail = estimateService.detail(created.estimateId(), ADMIN);
        assertThat(detail.status()).isEqualTo(EstimateStatus.DONE);
        // 조건을 만족하는 건 12·13대뿐이다 — 11대는 처리율 88 % 로 모자라고 14대부터는 가동률이 79 % 로
        // 목표에 못 미친다. 그 둘 중 효율 점수가 높은 13대가 권장이다
        // (12대 96 × 82 = 78.7, 13대 100 × 80.5 = 80.5)
        assertThat(detail.recommendedCount()).isEqualTo(13);
        assertThat(detail.reasonCode()).isNull();
        assertThat(detail.elapsedSeconds()).isNotNull();
        assertThat(detail.runs()).hasSize(MAX_AMR);
        assertThat(detail.runs()).extracting(EstimateDetailResponse.Run::status).containsOnly(RunStatus.DONE);
        assertThat(detail.runs().get(11).throughput()).isEqualTo(96.0);
        // 건/일 환산 배율은 (하루 물량 ÷ 보낸 건수)다 (S15P21A106-214). 하루치 주문을 통째로 실어
        // 보내므로 배율이 1이고, 실측 96건이 그대로 96건/일이다. 예전의 (실제 출고창 ÷ 시뮬 출고창)
        // 배율이던 시절에는 5시간 창고에서 ×1.25 로 부풀려 120 이 나왔다
        assertThat(detail.runs().get(11).outbound()).isEqualTo(96L);
        // 판정 밖 상세 지표도 run 마다 남는다 (S15P21A106-236)
        assertThat(detail.runs().get(11).kpi().ordersTotal()).isEqualTo(100);
        assertThat(detail.runs().get(11).kpi().throughputOrdersPerH()).isEqualTo(120.0);
        assertThat(detail.verification()).isNull();
    }

    @Test
    void verify_result_is_stored_and_compared_against_the_recommended_run() {
        EstimateCreateResponse created = estimateService.create(
new EstimateCreateRequest(warehouseId, null, null, null, null, null, null), ADMIN);
        for (int amrCount = 1; amrCount <= MAX_AMR; amrCount++) {
            estimateService.applyResult(done(created.estimateId(), amrCount));
        }

        // 권장 13대의 계산값: 시간당 130건 · p90 900초 · 혼잡 0.05. 검증은 p90 이 +15 % 라 기준(10 %)을 넘는다
        estimateService.applyVerifyResult(new VerifyResultResponse(
                "verify_" + created.estimateId(), "done", null, created.estimateId(),
                "est_%d_n13".formatted(created.estimateId()),
                new VerifyResultResponse.Artifacts("verify_%d/demo.mp4".formatted(created.estimateId()), null),
                new VerifyResultResponse.Verify(13, 13, 600, "window elapsed",
                        new VerifyResultResponse.Fms("done", null, null)),
                new SimulationResponse.Kpi(30, 28, 0, 0, 600L, 500.0, 1035.0, 40.0,
                        126.0, 140.0, 0.7, 0.055, 20_000L, 0L)));

        EstimateDetailResponse detail = estimateService.detail(created.estimateId(), ADMIN);
        EstimateDetailResponse.Verification verification = detail.verification();
        assertThat(verification.status()).isEqualTo("done");
        assertThat(verification.notice()).isEqualTo(VerifyNoticeCode.SLOWER_AT_PEAK);
        assertThat(verification.comparison().leadTimeP90S().expected()).isEqualTo(900.0);
        assertThat(verification.comparison().leadTimeP90S().diff()).isEqualTo(135.0);
        assertThat(verification.comparison().throughputOrdersPerH().expected()).isEqualTo(130.0);
        assertThat(estimateRepository.findById(created.estimateId()).orElseThrow().getVerify().getRobotsOnline())
                .isEqualTo(13);
    }

    @Test
    void one_failed_run_does_not_stop_the_rest() {
        EstimateCreateResponse created = estimateService.create(
new EstimateCreateRequest(warehouseId, null, null, null, null, null, null), ADMIN);

        for (int amrCount = 1; amrCount <= MAX_AMR; amrCount++) {
            if (amrCount != 12) {
                estimateService.applyResult(done(created.estimateId(), amrCount));
            }
        }
        estimateService.applyResult(new SimulationResponse(
                "est_%d_n12".formatted(created.estimateId()), "failed", "시뮬 정체 감지", null, null));

        EstimateDetailResponse detail = estimateService.detail(created.estimateId(), ADMIN);
        assertThat(detail.status()).isEqualTo(EstimateStatus.PARTIAL);
        // 권장 후보였던 12대가 빠져도 13대가 세 조건을 만족한다 (처리율 100 %, 가동률 80.5 %, 2.02억)
        assertThat(detail.recommendedCount()).isEqualTo(13);
        assertThat(detail.runs().get(11).status()).isEqualTo(RunStatus.FAILED);
        assertThat(detail.runs().get(11).error()).isEqualTo("시뮬 정체 감지");
    }

    @Test
    void a_redelivered_result_does_not_overwrite_the_first_one() {
        EstimateCreateResponse created = estimateService.create(
new EstimateCreateRequest(warehouseId, null, null, null, null, null, null), ADMIN);
        String runId = "est_%d_n3".formatted(created.estimateId());

        estimateService.applyResult(done(created.estimateId(), 3));
        estimateService.applyResult(new SimulationResponse(runId, "done", null,
                new SimulationResponse.Kpi(100, 1, null, null, null, null, null, null,
                        null, null, 0.01, null, null, null), null));

        SimScenario run = scenarioRepository.findByRunId(runId).orElseThrow();
        assertThat(run.getThroughput()).isEqualTo(24.0);   // 3대 첫 결과가 유지된다
        assertThat(run.getStatus()).isEqualTo(RunStatus.DONE);
    }

    @Test
    void a_stuck_run_is_recovered_by_the_timeout_sweep() {
        EstimateCreateResponse created = estimateService.create(
new EstimateCreateRequest(warehouseId, null, null, null, null, null, null), ADMIN);
        for (int amrCount = 1; amrCount < MAX_AMR; amrCount++) {
            estimateService.applyResult(done(created.estimateId(), amrCount));
        }
        // 마지막 대수 run 만 결과가 오지 않은 상태로 발행 시각을 과거로 돌린다
        jdbc.update("UPDATE simscenarios SET published_at = published_at - INTERVAL '2 hours' WHERE status = 'QUEUED'");

        assertThat(estimateService.sweepTimeouts()).isEqualTo(1);

        EstimateDetailResponse detail = estimateService.detail(created.estimateId(), ADMIN);
        assertThat(detail.runs().get(MAX_AMR - 1).status()).isEqualTo(RunStatus.TIMEOUT);
        assertThat(detail.status()).isEqualTo(EstimateStatus.PARTIAL);
        assertThat(detail.recommendedCount()).isEqualTo(13);   // 남은 결과로 판정은 그대로
    }

    /**
     * 대수가 늘면 처리율 +8 %p(100 % 에서 포화), 가동률 −1.5 %p.
     * 목표 95 % / 80 % 에서는 12~13대만 세 조건을 만족한다.
     */
    /** 상세 지표는 대수에 비례하는 가짜 값 — 시간당 10 × 대수 건, p90 은 대수가 늘면 짧아진다. */
    private SimulationResponse done(long estimateId, int amrCount) {
        SimulationResponse.Kpi kpi = new SimulationResponse.Kpi(
                100, Math.min(100, amrCount * 8), null, null,
                21_600L, 300.0, Math.max(60.0, 12_600.0 - amrCount * 900.0), 30.0,
                amrCount * 10.0, null,
                (100 - amrCount * 1.5) / 100.0, 0.05, 1_000L * amrCount, 0L);
        return new SimulationResponse("est_%d_n%d".formatted(estimateId, amrCount), "done", null, kpi, null);
    }
}
