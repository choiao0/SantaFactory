package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.repository.SimScenarioRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import com.ssafy.santafactory.service.SimulationService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.within;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EstimateServiceTest {

    private static final EstimateProperties PROPS =
            new EstimateProperties(15_000_000L, 5_000_000L, 500_000L, 8, 6, 4, 1, Duration.ofMinutes(30));

    @Mock
    EstimateRepository estimateRepository;
    @Mock
    SimScenarioRepository scenarioRepository;
    @Mock
    WarehouseRepository warehouseRepository;
    @Mock
    SimulationService simulationService;

    private final CostCalculator costCalculator = new CostCalculator(PROPS);
    private EstimateService service;

    private EstimateService service() {
        if (service == null) {
            service = new EstimateService(estimateRepository, scenarioRepository, warehouseRepository,
                    simulationService, costCalculator, new EstimateEvaluator(), PROPS);
        }
        return service;
    }

    // ── 생성 ─────────────────────────────────────────────────────────────────

    @Test
    void creates_runs_for_one_up_to_the_affordable_fleet_size() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);
        when(simulationService.publishRuns(any(), any())).thenReturn(List.of("est_77_n1"));

        EstimateCreateResponse response = service().create(
                new EstimateCreateRequest(1L, null, null, null, null));

        // 예산 3억이면 19대까지 살 수 있지만 상한 8이 먼저 걸린다
        assertThat(response.estimateId()).isEqualTo(77L);
        assertThat(response.maxAmrCount()).isEqualTo(8);
        verify(scenarioRepository, times(8)).save(any());

        ArgumentCaptor<List<Integer>> counts = ArgumentCaptor.captor();
        ArgumentCaptor<SimulationRequest> base = ArgumentCaptor.captor();
        verify(simulationService).publishRuns(base.capture(), counts.capture());
        assertThat(counts.getValue()).containsExactly(1, 2, 3, 4, 5, 6, 7, 8);
        assertThat(base.getValue().runId()).isEqualTo("est_77");
    }

    @Test
    void run_rows_carry_the_queue_key_and_the_cost_of_their_fleet_size() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);
        when(simulationService.publishRuns(any(), any())).thenReturn(List.of());

        service().create(new EstimateCreateRequest(1L, null, null, null, 50_000_000L));

        ArgumentCaptor<SimScenario> saved = ArgumentCaptor.captor();
        verify(scenarioRepository, times(4)).save(saved.capture());   // 5천만 / 1550만 = 3대 + 여유 1
        assertThat(saved.getAllValues()).extracting(SimScenario::getRunId)
                .containsExactly("est_77_n1", "est_77_n2", "est_77_n3", "est_77_n4");
        assertThat(saved.getAllValues()).extracting(SimScenario::getStatus)
                .containsOnly(RunStatus.QUEUED);
        assertThat(saved.getAllValues().get(3).getTotalCost()).isEqualTo(costCalculator.cost(4));
    }

    @Test
    void request_values_override_the_warehouse_defaults() {
        givenWarehouse(1L);
        ArgumentCaptor<Estimate> saved = ArgumentCaptor.captor();
        when(estimateRepository.save(saved.capture())).thenAnswer(call -> withId(call.getArgument(0), 77L));
        when(simulationService.publishRuns(any(), any())).thenReturn(List.of());

        service().create(new EstimateCreateRequest(1L, "geek.p40", 88.0, 70.0, 100_000_000L));

        assertThat(saved.getValue().getAmrModel()).isEqualTo("geek.p40");
        assertThat(saved.getValue().getTargetThroughput()).isEqualTo(88.0);
        assertThat(saved.getValue().getTargetUtilization()).isEqualTo(70.0);
        assertThat(saved.getValue().getBudgetLimit()).isEqualTo(100_000_000L);
    }

    @Test
    void rejects_an_unknown_warehouse() {
        when(warehouseRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service().create(new EstimateCreateRequest(99L, null, null, null, null)))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.WAREHOUSE_NOT_FOUND);
    }

    @Test
    void rejects_an_unknown_estimate_on_lookup() {
        when(estimateRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service().detail(99L))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.ESTIMATE_NOT_FOUND);
    }

    // ── 결과 반영 ────────────────────────────────────────────────────────────

    @Test
    void ignores_a_result_for_an_unknown_run() {
        when(scenarioRepository.findByRunId("est_9_n3")).thenReturn(Optional.empty());

        assertThatCode(() -> service().applyResult(done("est_9_n3", 100, 90, 0.9)))
                .doesNotThrowAnyException();

        verify(scenarioRepository, never()).findByEstimateIdOrderByAmrCountAsc(any());
    }

    @Test
    void ignores_a_second_result_for_a_run_already_finished() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario run = run(estimate, 4);
        run.markDone(85.0, 95.0, 85L);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));

        service().applyResult(done(run.getRunId(), 100, 10, 0.1));   // 다른 값으로 재전달

        assertThat(run.getThroughput()).isEqualTo(85.0);             // 첫 결과가 유지된다
        assertThat(run.getUtilization()).isEqualTo(95.0);
        verify(scenarioRepository, never()).findByEstimateIdOrderByAmrCountAsc(any());
    }

    @Test
    void waits_while_other_runs_are_still_pending() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario first = run(estimate, 2);
        SimScenario second = run(estimate, 4);
        when(scenarioRepository.findByRunId(first.getRunId())).thenReturn(Optional.of(first));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(first, second));

        service().applyResult(done(first.getRunId(), 100, 60, 0.98));

        assertThat(first.getStatus()).isEqualTo(RunStatus.DONE);
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.RUNNING);   // 아직 확정하지 않는다
        assertThat(estimate.getRecommendedCount()).isNull();
    }

    @Test
    void confirms_the_verdict_when_the_last_run_arrives() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario twoAmr = run(estimate, 2);
        SimScenario fourAmr = run(estimate, 4);
        SimScenario sixAmr = run(estimate, 6);
        twoAmr.markDone(60.0, 98.0, 60L);
        fourAmr.markDone(85.0, 95.0, 85L);
        when(scenarioRepository.findByRunId(sixAmr.getRunId())).thenReturn(Optional.of(sixAmr));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any()))
                .thenReturn(List.of(twoAmr, fourAmr, sixAmr));

        service().applyResult(done(sixAmr.getRunId(), 100, 95, 0.93));

        // 4대가 처리율 85 % · 가동률 95 % 로 3조건을 처음 만족한다
        assertThat(estimate.getRecommendedCount()).isEqualTo(4);
        assertThat(estimate.getReasonCode()).isNull();
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.DONE);
        assertThat(estimate.getCompletedAt()).isNotNull();
    }

    @Test
    void keeps_going_when_one_run_failed_and_marks_the_estimate_partial() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario twoAmr = run(estimate, 2);
        SimScenario fourAmr = run(estimate, 4);
        SimScenario sixAmr = run(estimate, 6);
        twoAmr.markDone(60.0, 98.0, 60L);
        fourAmr.markDone(85.0, 95.0, 85L);
        when(scenarioRepository.findByRunId(sixAmr.getRunId())).thenReturn(Optional.of(sixAmr));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any()))
                .thenReturn(List.of(twoAmr, fourAmr, sixAmr));

        service().applyResult(failed(sixAmr.getRunId(), "시뮬 정체 감지"));

        assertThat(sixAmr.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(sixAmr.getError()).isEqualTo("시뮬 정체 감지");
        assertThat(estimate.getRecommendedCount()).isEqualTo(4);              // 남은 결과로 판정
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.PARTIAL);
    }

    @Test
    void reports_all_failed_when_no_run_produced_a_result() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario twoAmr = run(estimate, 2);
        SimScenario fourAmr = run(estimate, 4);
        twoAmr.markFailed("맵 없음");
        when(scenarioRepository.findByRunId(fourAmr.getRunId())).thenReturn(Optional.of(fourAmr));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any()))
                .thenReturn(List.of(twoAmr, fourAmr));

        service().applyResult(failed(fourAmr.getRunId(), "맵 없음"));

        assertThat(estimate.getRecommendedCount()).isNull();
        assertThat(estimate.getReasonCode()).isEqualTo(ReasonCode.ALL_FAILED);
        // 전건 실패도 "일부 실패" 로 다룬다 — 명세 §3-4 의 견적 상태에 실패 값이 없다
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.PARTIAL);
    }

    @Test
    void treats_a_done_result_without_kpi_as_a_failure() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(run));

        service().applyResult(new SimulationResponse(run.getRunId(), "done", null, null));

        assertThat(run.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(run.getError()).isEqualTo("결과에 kpi 가 없음");
    }

    @Test
    void does_not_revive_a_cancelled_estimate() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        estimate.cancel();
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(run));

        service().applyResult(done(run.getRunId(), 100, 95, 0.95));

        assertThat(run.getStatus()).isEqualTo(RunStatus.DONE);                 // run 은 기록된다
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.CANCELLED);  // 견적은 되살아나지 않는다
        assertThat(estimate.getRecommendedCount()).isNull();
    }

    @Test
    void drops_a_run_whose_order_total_is_zero() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(run));

        service().applyResult(done(run.getRunId(), 0, 0, 0.5));   // 주문이 하나도 안 생긴 실행

        assertThat(run.getThroughput()).isNull();                 // 처리율을 계산할 수 없다
        assertThat(estimate.getReasonCode()).isEqualTo(ReasonCode.ALL_FAILED);
    }

    // ── TIMEOUT 스윕 ─────────────────────────────────────────────────────────

    @Test
    void sweep_does_nothing_when_no_run_is_overdue() {
        when(scenarioRepository.findByStatusInAndPublishedAtBefore(any(), any())).thenReturn(List.of());

        assertThat(service().sweepTimeouts()).isZero();
    }

    @Test
    void sweep_looks_back_by_the_configured_timeout() {
        when(scenarioRepository.findByStatusInAndPublishedAtBefore(any(), any())).thenReturn(List.of());

        service().sweepTimeouts();

        ArgumentCaptor<List<RunStatus>> statuses = ArgumentCaptor.captor();
        ArgumentCaptor<LocalDateTime> threshold = ArgumentCaptor.captor();
        verify(scenarioRepository).findByStatusInAndPublishedAtBefore(statuses.capture(), threshold.capture());
        assertThat(statuses.getValue()).containsExactly(RunStatus.QUEUED, RunStatus.RUNNING);
        assertThat(threshold.getValue()).isCloseTo(LocalDateTime.now().minusMinutes(30),
                within(5, ChronoUnit.SECONDS));
    }

    @Test
    void sweep_times_out_a_stuck_run_and_finalizes_the_estimate() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario twoAmr = run(estimate, 2);
        SimScenario fourAmr = run(estimate, 4);
        SimScenario sixAmr = run(estimate, 6);
        twoAmr.markDone(60.0, 98.0, 60L);
        fourAmr.markDone(85.0, 95.0, 85L);
        when(scenarioRepository.findByStatusInAndPublishedAtBefore(any(), any())).thenReturn(List.of(sixAmr));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any()))
                .thenReturn(List.of(twoAmr, fourAmr, sixAmr));

        assertThat(service().sweepTimeouts()).isEqualTo(1);

        assertThat(sixAmr.getStatus()).isEqualTo(RunStatus.TIMEOUT);
        assertThat(estimate.getRecommendedCount()).isEqualTo(4);              // 남은 결과로 판정
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.PARTIAL);
    }

    @Test
    void sweep_reports_all_failed_when_every_run_is_stuck() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario twoAmr = run(estimate, 2);
        SimScenario fourAmr = run(estimate, 4);
        when(scenarioRepository.findByStatusInAndPublishedAtBefore(any(), any()))
                .thenReturn(List.of(twoAmr, fourAmr));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any()))
                .thenReturn(List.of(twoAmr, fourAmr));

        assertThat(service().sweepTimeouts()).isEqualTo(2);

        // 같은 견적의 run 두 건이지만 판정은 한 번만 확정된다 (distinct)
        verify(scenarioRepository, times(1)).findByEstimateIdOrderByAmrCountAsc(any());
        assertThat(estimate.getReasonCode()).isEqualTo(ReasonCode.ALL_FAILED);
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.PARTIAL);
    }

    // ── 픽스처 ────────────────────────────────────────────────────────────────

    /** 창고 시드 값(품고): 작업자 12명, 목표 처리율 95 %, 가동률 80 %, 예산 3억. */
    private void givenWarehouse(long warehouseId) {
        Warehouse warehouse = mock(Warehouse.class);
        lenient().when(warehouse.getTargetThroughput()).thenReturn(95.0);
        lenient().when(warehouse.getTargetUtilization()).thenReturn(80.0);
        lenient().when(warehouse.getBudgetLimit()).thenReturn(300_000_000L);
        lenient().when(warehouse.getWorkerCount()).thenReturn(12);
        lenient().when(warehouse.getInboundStart()).thenReturn(LocalDateTime.of(2026, 1, 1, 1, 0));
        lenient().when(warehouse.getInboundEnd()).thenReturn(LocalDateTime.of(2026, 1, 1, 9, 0));
        lenient().when(warehouse.getOutboundStart()).thenReturn(LocalDateTime.of(2026, 1, 1, 13, 0));
        lenient().when(warehouse.getOutboundEnd()).thenReturn(LocalDateTime.of(2026, 1, 1, 18, 0));
        lenient().when(warehouse.getInboundAvg()).thenReturn(600L);
        lenient().when(warehouse.getOutboundAvg()).thenReturn(800L);
        when(warehouseRepository.findById(warehouseId)).thenReturn(Optional.of(warehouse));
    }

    /** save() 가 PK 를 채워 돌려주는 것을 흉내낸다 — run_id 접두사가 견적 번호로 만들어진다. */
    private void givenSavedEstimateId(long estimateId) {
        when(estimateRepository.save(any())).thenAnswer(call -> withId(call.getArgument(0), estimateId));
    }

    private Estimate withId(Estimate estimate, long id) {
        ReflectionTestUtils.setField(estimate, "id", id);
        return estimate;
    }

    private Estimate estimate(double targetThroughput, double targetUtilization, long budgetLimit) {
        return Estimate.open(mock(Warehouse.class), "iw.hub", targetThroughput, targetUtilization, budgetLimit);
    }

    private SimScenario run(Estimate estimate, int amrCount) {
        return SimScenario.queued(estimate, "est_1_n" + amrCount, amrCount, costCalculator.cost(amrCount));
    }

    private SimulationResponse done(String runId, int ordersTotal, int ordersCompleted, double amrUtilization) {
        SimulationResponse.Kpi kpi = new SimulationResponse.Kpi(
                ordersTotal, ordersCompleted, null, null,
                null, null, null, null,
                null, null,
                amrUtilization, null, null, null);
        return new SimulationResponse(runId, "done", null, kpi);
    }

    private SimulationResponse failed(String runId, String error) {
        return new SimulationResponse(runId, "failed", error, null);
    }
}
