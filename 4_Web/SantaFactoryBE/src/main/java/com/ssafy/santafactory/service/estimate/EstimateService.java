package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateSummaryResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.repository.SimScenarioRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import com.ssafy.santafactory.service.SimulationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.stream.IntStream;

/**
 * 견적 생성·조회, 그리고 시뮬 결과 반영.
 *
 * <p>생성은 대수 1~최대까지 run 을 만들어 큐에 발행하고, 결과가 하나씩 돌아오면 그 run 만 갱신한다.
 * 마지막 run 이 끝나면 곡선 전체로 판정을 확정한다. 실패는 해당 run 에 격리되어 나머지 대수는
 * 계속 진행한다(지라 S15P21A106-82 완료 조건).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EstimateService {

    /** 시뮬 시각 필드는 "HH:mm" 문자열이다 (명세 §1-1). */
    private static final DateTimeFormatter HH_MM = DateTimeFormatter.ofPattern("HH:mm");

    /** 시뮬은 결정론이라 시드를 고정해 두면 같은 견적이 같은 결과를 낸다. 시드 개수는 미확정. */
    private static final long FIXED_SEED = 42L;

    private final EstimateRepository estimateRepository;
    private final SimScenarioRepository scenarioRepository;
    private final WarehouseRepository warehouseRepository;
    private final SimulationService simulationService;
    private final CostCalculator costCalculator;
    private final EstimateEvaluator evaluator;

    // ── 생성 ─────────────────────────────────────────────────────────────────

    /**
     * 견적을 만들고 대수별 run 을 전부 발행한다.
     *
     * <p>run 행을 먼저 저장하고 발행한다. 발행이 실패하면 트랜잭션이 롤백돼 견적도 남지 않고
     * 호출자에게 503 이 간다(명세 §1-4).
     */
    @Transactional
    public EstimateCreateResponse create(EstimateCreateRequest request) {
        Warehouse warehouse = warehouseRepository.findById(request.warehouseId())
                .orElseThrow(() -> new GlobalException(ErrorCode.WAREHOUSE_NOT_FOUND));

        double targetThroughput = orDefault(request.targetThroughput(), warehouse.getTargetThroughput());
        double targetUtilization = orDefault(request.targetUtilization(), warehouse.getTargetUtilization());
        long budgetLimit = orDefault(request.budgetLimit(), warehouse.getBudgetLimit());

        Estimate estimate = estimateRepository.save(Estimate.open(
                warehouse, request.amrModelOrDefault(), targetThroughput, targetUtilization, budgetLimit));

        int maxAmrCount = costCalculator.maxAmrCount(budgetLimit);
        String baseRunId = "est_" + estimate.getId();
        List<Integer> amrCounts = IntStream.rangeClosed(1, maxAmrCount).boxed().toList();

        for (int amrCount : amrCounts) {
            scenarioRepository.save(SimScenario.queued(
                    estimate, SimulationService.runId(baseRunId, amrCount), amrCount, costCalculator.cost(amrCount)));
        }
        List<String> runIds = simulationService.publishRuns(baseRequest(baseRunId, warehouse), amrCounts);

        log.info("견적 생성: estimateId={}, 최대 {}대, 목표 처리율 {}%, 가동률 {}%, 예산 {}원",
                estimate.getId(), maxAmrCount, targetThroughput, targetUtilization, budgetLimit);
        return new EstimateCreateResponse(estimate.getId(), maxAmrCount, runIds);
    }

    /**
     * 대수만 바꿔 발행할 기준 요청.
     *
     * <p>AMR 사양(속도·배터리·소모량)과 주문 목록은 비워 둔다 — 시뮬이 자체 기본값과 주문 스트림을
     * 쓰기 때문이다. 운영조건을 시뮬 인자(고정 시간·도착 간격)로 어떻게 환산할지는 아직 미합의라
     * 창고 값을 그대로 실어 보낸다.
     */
    private SimulationRequest baseRequest(String baseRunId, Warehouse warehouse) {
        SimulationRequest.Warehouse conditions = new SimulationRequest.Warehouse(
                warehouse.getWorkerCount(),
                format(warehouse.getInboundStart()),
                format(warehouse.getInboundEnd()),
                format(warehouse.getOutboundStart()),
                format(warehouse.getOutboundEnd()),
                toInt(warehouse.getInboundAvg()),
                toInt(warehouse.getOutboundAvg()));
        SimulationRequest.Amr amr =
                new SimulationRequest.Amr(0, null, null, null, null, null, null, null);
        return new SimulationRequest(baseRunId, FIXED_SEED, conditions, amr, List.of(), List.of());
    }

    // ── 조회 ─────────────────────────────────────────────────────────────────

    @Transactional(readOnly = true)
    public EstimateDetailResponse detail(Long estimateId) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        return EstimateDetailResponse.of(estimate, scenarioRepository.findByEstimateIdOrderByAmrCountAsc(estimateId));
    }

    @Transactional(readOnly = true)
    public Page<EstimateSummaryResponse> list(Pageable pageable) {
        return estimateRepository.findAllByOrderByCreatedAtDesc(pageable).map(EstimateSummaryResponse::from);
    }

    /** 견적 취소. 이미 큐에 들어간 run 의 결과가 와도 판정은 확정되지 않는다. */
    @Transactional
    public void cancel(Long estimateId) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        estimate.cancel();
        log.info("견적 취소: estimateId={}, status={}", estimateId, estimate.getStatus());
    }

    // ── 결과 반영 ────────────────────────────────────────────────────────────

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

    // ── 잡동사니 ─────────────────────────────────────────────────────────────

    private double orDefault(Double requested, Double fallback) {
        return requested != null ? requested : fallback;
    }

    private long orDefault(Long requested, Long fallback) {
        return requested != null ? requested : fallback;
    }

    private String format(LocalDateTime time) {
        return time == null ? null : time.format(HH_MM);
    }

    private Integer toInt(Long value) {
        return value == null ? null : value.intValue();
    }
}
