package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateFinished;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateVerified;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunUpdated;
import com.ssafy.santafactory.dto.estimate.EstimateSummaryResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.dto.simulation.VerifyResultResponse;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.RunStatus;
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
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.concurrent.TimeUnit;
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

    /** 시뮬 평가 시드 */
    private static final long FIXED_SEED = 101L;

    /** 아직 결과를 기다리는 상태 — TIMEOUT 스윕 대상. */
    private static final List<RunStatus> PENDING = List.of(RunStatus.QUEUED, RunStatus.RUNNING);

    private final EstimateRepository estimateRepository;
    private final SimScenarioRepository scenarioRepository;
    private final WarehouseRepository warehouseRepository;
    private final SimulationService simulationService;
    private final CostCalculator costCalculator;
    private final EstimateEvaluator evaluator;
    private final EstimateProperties properties;
    private final ApplicationEventPublisher eventPublisher;

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

        List<Integer> amrCounts = amrCounts(request, budgetLimit);
        int maxAmrCount = amrCounts.get(amrCounts.size() - 1);
        String baseRunId = "est_" + estimate.getId();

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
     * 돌릴 대수 목록.
     *
     * <p>프론트가 범위(min·max)를 보내면 그 범위를 1대 간격으로, 안 보내면 1대부터 예산으로 살 수 있는
     * 대수까지 전부. 어느 쪽이든 충전 존 상한({@code max-amr-count})을 넘는 대수는 자른다 — 넘겨
     * 발행하면 시뮬이 배치 단계에서 죽는다. 범위 최소가 상한보다 크면 돌릴 게 없으므로 400 이다.
     */
    private List<Integer> amrCounts(EstimateCreateRequest request, long budgetLimit) {
        if (!request.hasFleetRange()) {
            return IntStream.rangeClosed(1, costCalculator.maxAmrCount(budgetLimit)).boxed().toList();
        }
        int cap = properties.maxAmrCount();
        List<Integer> counts = IntStream.rangeClosed(request.fleetMin(), Math.min(request.fleetMax(), cap))
                .boxed().toList();
        if (counts.isEmpty()) {
            log.warn("대수 범위가 상한을 넘음: min={}, max={}, cap={}", request.fleetMin(), request.fleetMax(), cap);
            throw new GlobalException(ErrorCode.VALIDATION_ERROR);
        }
        return counts;
    }

    /**
     * 대수만 바꿔 발행할 기준 요청.
     *
     * <p><b>실행 시간을 명시한다.</b> 안 보내면 시뮬이 유한 주문 모드로 돌아 처리율이 전 대수 100 % 가
     * 되고 견적이 "1대 권장" 같은 틀린 답을 낸다. 실행 시간은 성능 제약(견적 1회 90초)으로 정해지는
     * 값이라 창고 데이터가 아니라 설정({@code estimate.horizon})에서 온다.
     *
     * <p>도착 간격은 창고의 <b>작업 시간 기준</b>으로 계산한다 — 하루 물량을 실제 작업창으로 나눈
     * 도착률이다(입고 600건 / 8시간 → 48초). 시간만 줄이고 간격은 유지하므로 부하 밀도가 보존된다.
     *
     * <p>AMR 사양(속도·배터리·소모량)과 주문 목록은 비워 둔다 — 시뮬이 자체 기본값과 주문 스트림을 쓴다.
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
        return new SimulationRequest(
                baseRunId,
                FIXED_SEED,
                properties.horizon().toSeconds(),
                properties.shifts(),
                gapSeconds(warehouse.getInboundAvg(), warehouse.getInboundStart(), warehouse.getInboundEnd()),
                gapSeconds(warehouse.getOutboundAvg(), warehouse.getOutboundStart(), warehouse.getOutboundEnd()),
                conditions, amr, List.of(), List.of());
    }

    /**
     * 하루 물량 ÷ 작업창 = 도착률, 그 역수가 평균 도착 간격(초).
     * 작업창을 알 수 없으면(창고 종료 시각이 비어 있으면) 하루 24시간 균등으로 본다.
     */
    private Double gapSeconds(Long dailyCount, LocalDateTime start, LocalDateTime end) {
        if (dailyCount == null || dailyCount <= 0) {
            return null;
        }
        return (double) windowSeconds(start, end) / dailyCount;
    }

    /**
     * 작업창 길이(초).
     *
     * <p>야간 교대(22:00 → 06:00)를 같은 날짜로 저장하면 종료가 시작보다 앞서는데, 그건 자정을 넘긴
     * 것이므로 하루를 더해 읽는다. 이걸 24시간으로 폴백하면 도착 간격이 3배 느슨해져 부하가
     * 과소 추정된다. 시각이 아예 없으면 하루 24시간 균등으로 본다.
     */
    private long windowSeconds(LocalDateTime start, LocalDateTime end) {
        if (start == null || end == null) {
            return Duration.ofDays(1).toSeconds();
        }
        Duration window = Duration.between(start, end);
        if (window.isNegative()) {
            window = window.plusDays(1);
        }
        return window.isZero() ? Duration.ofDays(1).toSeconds() : window.toSeconds();
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
        if (estimate.isCancelled()) {
            eventPublisher.publishEvent(finishedEvent(estimate));
        }
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
        eventPublisher.publishEvent(new RunUpdated(run.getEstimate().getId(), EstimateDetailResponse.Run.from(run)));

        finalizeIfComplete(run.getEstimate());
    }

    // ── 물리 검증 결과 반영 ──────────────────────────────────────────────────

    /**
     * 물리 검증(Isaac) 결과를 반영한다. 영상 URL 이 있으면 저장하고, 성패와 무관하게 SSE 로 알린다.
     *
     * <p>모르는 견적 id 는 무시한다. 같은 결과가 두 번 와도(명세 §1-3과 동일한 중복 허용) 같은 값을
     * 다시 쓸 뿐이라 별도 처리 없이 안전하다 — DES 의 run 처럼 상태를 갖는 하위 엔티티가 없어서다.
     */
    @Transactional
    public void applyVerifyResult(VerifyResultResponse response) {
        if (response.estimateId() == null) {
            log.warn("estimate_id 없는 검증 결과 무시: runId={}", response.runId());
            return;
        }
        Estimate estimate = estimateRepository.findById(response.estimateId()).orElse(null);
        if (estimate == null) {
            log.warn("모르는 견적의 검증 결과 무시: estimateId={}, runId={}",
                    response.estimateId(), response.runId());
            return;
        }
        String videoUrl = response.artifacts() != null ? response.artifacts().video() : null;
        if (videoUrl != null) {
            estimate.applyVerifyVideo(videoUrl);
        }
        log.info("물리 검증 결과 반영: estimateId={}, status={}, video={}",
                estimate.getId(), response.status(), videoUrl);
        eventPublisher.publishEvent(
                new EstimateVerified(estimate.getId(), response.status(), videoUrl, response.error()));
    }

    /**
     * 결과가 오지 않는 run 을 TIMEOUT 으로 정리한다.
     *
     * <p>이게 없으면 워커가 죽거나 발행 메시지가 유실될 때 그 run 이 QUEUED 에 갇히고, 견적이 영원히
     * RUNNING 으로 남는다. 발행은 트랜잭션 커밋보다 먼저 일어나므로(생성 참고) 아주 빠른 워커가
     * 커밋 전에 응답해 결과가 버려지는 경우도 여기서 회수된다.
     *
     * @return TIMEOUT 처리한 run 수
     */
    @Scheduled(fixedDelayString = "${estimate.timeout-sweep-interval:60}", timeUnit = TimeUnit.SECONDS)
    @Transactional
    public int sweepTimeouts() {
        LocalDateTime threshold = LocalDateTime.now().minus(properties.runTimeout());
        List<SimScenario> stuck = scenarioRepository.findByStatusInAndPublishedAtBefore(PENDING, threshold);
        if (stuck.isEmpty()) {
            return 0;
        }

        stuck.forEach(SimScenario::markTimeout);
        stuck.forEach(run -> eventPublisher.publishEvent(
                new RunUpdated(run.getEstimate().getId(), EstimateDetailResponse.Run.from(run))));
        // 같은 견적의 run 들은 한 영속성 컨텍스트에서 같은 인스턴스라 distinct 로 중복 판정을 막는다
        stuck.stream().map(SimScenario::getEstimate).distinct().forEach(this::finalizeIfComplete);

        log.warn("결과가 오지 않은 run {}건 TIMEOUT 처리: 기준 시각={}, runIds={}",
                stuck.size(), threshold, stuck.stream().map(SimScenario::getRunId).toList());
        return stuck.size();
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
        run.markDone(throughputPercent(kpi), utilizationPercent(kpi), dailyOutbound(run, kpi));
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
     * 출고 처리 건수를 <b>건/일</b>로 환산한다 ({@code SimScenarios.outbound} 단위).
     *
     * <p>시뮬은 horizon 중 출고 구간(기본 4시간)만 출고를 받는데, 도착 간격은 실제 도착률을 그대로
     * 쓰므로 실측 건수 × (실제 출고창 ÷ 시뮬 출고창) 이 하루 물량이 된다. 기본 설정이면 배율 1.25다
     * (실제 5시간 ÷ 시뮬 4시간). 하루 전량 실행(horizon 24h)으로 바꾸면 배율이 1에 가까워진다.
     *
     * <p>창고 출고창을 알 수 없으면 환산 근거가 없으므로 실측값을 그대로 남긴다.
     */
    private Long dailyOutbound(SimScenario run, SimulationResponse.Kpi kpi) {
        Integer completed = kpi.ordersCompleted();
        if (completed == null) {
            return null;
        }
        Warehouse warehouse = run.getEstimate().getWarehouse();
        LocalDateTime start = warehouse.getOutboundStart();
        LocalDateTime end = warehouse.getOutboundEnd();
        long simulated = properties.simulatedOutboundSeconds();
        if (start == null || end == null || !end.isAfter(start) || simulated <= 0) {
            return completed.longValue();
        }
        return Math.round(completed * (double) Duration.between(start, end).toSeconds() / simulated);
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
        eventPublisher.publishEvent(finishedEvent(estimate));
    }

    private EstimateFinished finishedEvent(Estimate estimate) {
        return new EstimateFinished(estimate.getId(), estimate.getStatus(),
                estimate.getRecommendedCount(), estimate.getKneeCount(), estimate.getReasonCode());
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
