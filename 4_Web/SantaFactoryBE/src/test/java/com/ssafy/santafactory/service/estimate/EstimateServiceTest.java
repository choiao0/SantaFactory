package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.repository.SimScenarioRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EstimateServiceTest {

    private static final EstimateProperties PROPS =
            new EstimateProperties(15_000_000L, 5_000_000L, 500_000L, 8, 6, 4, 1);

    @Mock
    SimScenarioRepository scenarioRepository;

    private final CostCalculator costCalculator = new CostCalculator(PROPS);
    private EstimateService service;

    private EstimateService service() {
        if (service == null) {
            service = new EstimateService(scenarioRepository, new EstimateEvaluator());
        }
        return service;
    }

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

    // ── 픽스처 ────────────────────────────────────────────────────────────────

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
