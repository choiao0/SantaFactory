package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import com.ssafy.santafactory.repository.SimScenarioRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 시뮬 결과를 견적에 반영한다.
 *
 * <p>run 1건이 도착하면 그 run 만 갱신하고, 그 견적의 마지막 run 이었으면 곡선 전체로 판정을 확정한다.
 * 실패는 해당 run 에 격리되어 나머지 대수는 계속 진행한다(지라 S15P21A106-82 완료 조건).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EstimateService {

    private final SimScenarioRepository scenarioRepository;
    private final EstimateEvaluator evaluator;

    @Transactional
    public void applyResult(SimulationResponse response) {
        SimScenario run = scenarioRepository.findByRunId(response.runId()).orElse(null);
        if (run == null) {
            log.warn("모르는 run 결과 무시: runId={}", response.runId());
            return;
        }
        if (run.isFinished()) {
            log.info("이미 처리된 run 결과 무시: runId={}, status={}", run.getRunId(), run.getStatus());
            return;   // 같은 run_id 가 두 번 올 수 있다 (명세 §1-3)
        }

        if (isFailure(response)) {
            log.warn("시뮬 실패: runId={}, error={}", run.getRunId(), response.error());
            run.markFailed(response.error());
        } else {
            applyKpi(run, response.kpi());
        }

        finalizeIfComplete(run.getEstimate());
    }

    private boolean isFailure(SimulationResponse response) {
        return !"done".equals(response.status());
    }

    private void applyKpi(SimScenario run, SimulationResponse.Kpi kpi) {
        if (kpi == null) {
            log.warn("done 인데 kpi 가 없음: runId={}", run.getRunId());
            run.markFailed("결과에 kpi 가 없음");
            return;
        }
        run.markDone(throughputPercent(kpi), utilizationPercent(kpi), completedOrders(kpi));
        log.info("run 완료: runId={}, 처리율={}%, 가동률={}%",
                run.getRunId(), run.getThroughput(), run.getUtilization());
    }

    /**
     * 출고 처리율 % — 접수 주문 중 완료 비율.
     *
     * <p>단위 변환이 일어나는 유일한 지점이다. 유한 주문 모드로 돌리면 이 값이 항상 100 % 가 되므로
     * (주문을 다 처리하고 종료하니까) 고정 시간 모드 실행이 전제다 — 시뮬 실행 모드는 미확정.
     */
    private Double throughputPercent(SimulationResponse.Kpi kpi) {
        Integer total = kpi.ordersTotal();
        Integer completed = kpi.ordersCompleted();
        if (total == null || completed == null || total == 0) {
            return null;
        }
        return completed * 100.0 / total;
    }

    /** 시뮬은 0~1 로 주고 DB·판정은 % 를 쓴다. */
    private Double utilizationPercent(SimulationResponse.Kpi kpi) {
        return kpi.amrUtilization() == null ? null : kpi.amrUtilization() * 100.0;
    }

    /**
     * 출고 처리 건수. ERD 단위는 건/일인데 시뮬 실행 시간이 하루가 아니라서,
     * 지금은 완료 주문 수를 그대로 넣는다 — 일 단위 환산은 실행 시간(horizon)이 확정된 뒤에.
     */
    private Long completedOrders(SimulationResponse.Kpi kpi) {
        return kpi.ordersCompleted() == null ? null : kpi.ordersCompleted().longValue();
    }

    /** 미완료 run 이 없으면 판정을 확정한다. 하나라도 남아 있으면 아무것도 하지 않는다. */
    private void finalizeIfComplete(Estimate estimate) {
        List<SimScenario> runs = scenarioRepository.findByEstimateIdOrderByAmrCountAsc(estimate.getId());
        if (runs.isEmpty() || runs.stream().anyMatch(run -> !run.isFinished())) {
            return;
        }

        List<RunResult> results = runs.stream()
                .filter(SimScenario::hasKpi)
                .map(this::toRunResult)
                .toList();
        EstimateGoal goal = new EstimateGoal(
                estimate.getTargetThroughput(), estimate.getTargetUtilization(), estimate.getBudgetLimit());

        EstimateVerdict verdict = evaluator.evaluate(results, goal);
        boolean anyFailed = results.size() != runs.size();
        estimate.complete(verdict.recommendedCount(), verdict.kneeCount(), verdict.reasonCode(), anyFailed);

        log.info("견적 판정 확정: estimateId={}, 권장={}대, 무릎={}대, 사유={}, 상태={}",
                estimate.getId(), verdict.recommendedCount(), verdict.kneeCount(),
                verdict.reasonCode(), estimate.getStatus());
    }

    private RunResult toRunResult(SimScenario run) {
        return new RunResult(
                run.getAmrCount(),
                run.getThroughput(),
                run.getUtilization(),
                run.getTotalCost() == null ? 0L : run.getTotalCost());
    }
}
