package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateFinished;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateVerified;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunUpdated;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunsQueued;
import com.ssafy.santafactory.dto.estimate.EstimateSummaryResponse;
import com.ssafy.santafactory.dto.simulation.PhysicsMetrics;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.dto.simulation.VerifyRequest;
import com.ssafy.santafactory.dto.simulation.VerifyResultResponse;
import com.ssafy.santafactory.dto.simulation.VerifySliceMeta;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.service.estimate.quote.QuoteSource;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateVerification;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.estimate.VerifyRunStatus;
import com.ssafy.santafactory.entity.estimate.VerifySnapshot;
import com.ssafy.santafactory.entity.simulation.RunKpiDetail;
import com.ssafy.santafactory.entity.simulation.RunReplay;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import com.ssafy.santafactory.entity.simulation.SimScenarioVerifySlice;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.global.auth.OwnershipGuard;
import com.ssafy.santafactory.global.auth.TrialMode;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.repository.EstimateVerificationRepository;
import com.ssafy.santafactory.repository.RunReplayRepository;
import com.ssafy.santafactory.repository.SimScenarioRepository;
import com.ssafy.santafactory.repository.SimScenarioVerifySliceRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import com.ssafy.santafactory.service.SimulationService;
import com.ssafy.santafactory.service.estimate.ordergen.OutboundOrderGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
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

    /** 리플레이에서 맵을 담는 키. 저장할 때 떼어내고 조회할 때 다시 붙이므로 양쪽이 같아야 한다. */
    private static final String REPLAY_SCENE = "scene";

    /** 아직 결과를 기다리는 상태 — TIMEOUT 스윕 대상. */
    private static final List<RunStatus> PENDING = List.of(RunStatus.QUEUED, RunStatus.RUNNING);

    /** 대수별 물리 검증 중 아직 끝나지 않은 상태 — 중복 요청 가드·verify.done 판단에 쓴다 (S15P21A106-244). */
    private static final List<VerifyRunStatus> VERIFY_PENDING = List.of(VerifyRunStatus.PENDING, VerifyRunStatus.RUNNING);

    /** 워커가 run 을 집었을 때 결과 큐로 먼저 보내는 상태값 (명세 §1-2). */
    private static final String STATUS_RUNNING = "running";

    private final EstimateRepository estimateRepository;
    private final SimScenarioRepository scenarioRepository;
    private final RunReplayRepository replayRepository;
    private final WarehouseRepository warehouseRepository;
    private final SimulationService simulationService;
    private final CostCalculator costCalculator;
    private final EstimateEvaluator evaluator;
    private final EstimateProperties properties;
    private final OwnershipGuard ownershipGuard;
    private final ApplicationEventPublisher eventPublisher;
    private final OutboundOrderGenerator outboundOrderGenerator;
    private final ObjectMapper objectMapper;
    private final VerifyVideoPresigner videoPresigner;
    private final VerifyComparator verifyComparator;
    private final SimScenarioVerifySliceRepository sliceRepository;
    private final EstimateVerificationRepository verificationRepository;
    private final TrialMode trialMode;

    // ── 생성 ─────────────────────────────────────────────────────────────────

    /**
     * 견적을 만들고 대수별 run 을 전부 발행한다.
     *
     * <p>run 행을 저장하고 커밋한 뒤에 발행한다({@link RunsQueued} → {@link SimRequestDispatcher}).
     * 발행이 실패한 run 은 {@link #failUnpublished} 가 FAILED 로 닫는다.
     */
    @Transactional
    public EstimateCreateResponse create(EstimateCreateRequest request, AuthenticatedMember me) {
        trialMode.rejectNewRequests();   // 체험 모드는 견적 행도 만들지 않는다 — 워커에 갈 일이 없다 (S15P21A106-283)
        Warehouse warehouse = warehouseRepository.findById(request.warehouseId())
                .orElseThrow(() -> new GlobalException(ErrorCode.WAREHOUSE_NOT_FOUND));
        // 남의 창고로 견적을 만들지 못하게. 견적의 주인은 창고의 주인이다
        ownershipGuard.checkWarehouse(warehouse, me);

        double targetThroughput = orDefault(request.targetThroughput(), warehouse.getTargetThroughput());
        double targetUtilization = orDefault(request.targetUtilization(), warehouse.getTargetUtilization());
        long budgetLimit = orDefault(request.budgetLimit(), warehouse.getBudgetLimit());

        Estimate estimate = estimateRepository.save(Estimate.open(
                warehouse, request.amrModelOrDefault(), targetThroughput, targetUtilization, budgetLimit));

        List<Integer> amrCounts = amrCounts(request, budgetLimit);
        int maxAmrCount = amrCounts.get(amrCounts.size() - 1);
        String baseRunId = "est_" + estimate.getId();

        List<SimulationRequest.Outbound> outboundOrders = outboundOrderGenerator.generate(
                warehouse, properties.horizon().toSeconds(), outboundOrderCount(warehouse), FIXED_SEED);
        estimate.applyOutboundOrders(toJson(outboundOrders));

        for (int amrCount : amrCounts) {
            scenarioRepository.save(SimScenario.queued(
                    estimate, SimulationService.runId(baseRunId, amrCount), amrCount, costCalculator.cost(amrCount)));
        }
        eventPublisher.publishEvent(
                new RunsQueued(estimate.getId(), baseRequest(baseRunId, warehouse, outboundOrders), amrCounts));

        log.info("견적 생성: estimateId={}, 최대 {}대, 목표 처리율 {}%, 가동률 {}%, 예산 {}원",
                estimate.getId(), maxAmrCount, targetThroughput, targetUtilization, budgetLimit);
        List<String> runIds = amrCounts.stream().map(count -> SimulationService.runId(baseRunId, count)).toList();
        return new EstimateCreateResponse(estimate.getId(), maxAmrCount, runIds);
    }

    /**
     * 요청 큐에 발행하지 못한 run 을 FAILED 로 닫는다. 커밋 뒤 발행 단계에서 부르므로 새 트랜잭션이 필요하다.
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void failUnpublished(Long estimateId, List<Integer> amrCounts, String error) {
        List<SimScenario> runs = scenarioRepository.findByEstimateIdOrderByAmrCountAsc(estimateId).stream()
                .filter(run -> amrCounts.contains(run.getAmrCount()) && !run.isFinished())
                .toList();
        if (runs.isEmpty()) {
            return;
        }
        runs.forEach(run -> run.markFailed(error));
        runs.forEach(run -> eventPublisher.publishEvent(new RunUpdated(estimateId, EstimateDetailResponse.Run.from(run))));
        log.error("발행 실패 run {}건 FAILED 처리: estimateId={}, amrCounts={}", runs.size(), estimateId, amrCounts);
        finalizeIfComplete(runs.get(0).getEstimate());
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
     * <p>AMR 사양(속도·배터리·소모량)은 비워 둔다 — 시뮬이 자체 기본값을 쓴다. 단 왕복당 토트 수({@code capacity})는
     * 반드시 보낸다 — 시뮬 기본값이 1 이라 비우면 견적이 3~4배 비관적으로 나온다 (S15P21A106-218). 출고 주문은 이제 백엔드가
     * 생성한 목록을 그대로 싣는다({@code outboundOrderGenerator}) — 대수마다 다시 생성하지 않고 호출자가
     * 넘긴 같은 리스트를 재사용해야 대수별 비교가 의미 있다. 입고는 여전히 간격(gap) 기반이다.
     */
    private SimulationRequest baseRequest(
            String baseRunId, Warehouse warehouse, List<SimulationRequest.Outbound> outboundOrders) {
        SimulationRequest.Warehouse conditions = new SimulationRequest.Warehouse(
                warehouse.getWorkerCount(),
                format(warehouse.getInboundStart()),
                format(warehouse.getInboundEnd()),
                format(warehouse.getOutboundStart()),
                format(warehouse.getOutboundEnd()),
                toInt(warehouse.getInboundAvg()),
                toInt(warehouse.getOutboundAvg()));
        SimulationRequest.Amr amr =
                new SimulationRequest.Amr(0, null, null, null, null, null, null, properties.amrCapacity());
        return new SimulationRequest(
                baseRunId,
                FIXED_SEED,
                properties.horizon().toSeconds(),
                properties.shifts(),
                gapSeconds(warehouse.getInboundAvg(), warehouse.getInboundStart(), warehouse.getInboundEnd()),
                gapSeconds(warehouse.getOutboundAvg(), warehouse.getOutboundStart(), warehouse.getOutboundEnd()),
                conditions, amr, List.of(), outboundOrders,
                // 화면에서 대수별 주행을 재생하려면 run 마다 궤적이 있어야 한다 (S15P21A106-205).
                // 나중에 다시 돌려서 얻을 수 없다 — 그러려면 견적과 같은 6시간을 또 돌려야 하고,
                // 짧게 돌리면 --shifts 가 horizon 을 등분하므로 다른 시나리오가 된다
                properties.exportReplay());
    }

    /** 생성할 출고 주문 건수 — 창고의 하루 출고 물량, 없으면 파이썬 쪽과 같은 기본값(500). */
    private int outboundOrderCount(Warehouse warehouse) {
        Long outboundAvg = warehouse.getOutboundAvg();
        return outboundAvg != null && outboundAvg > 0 ? outboundAvg.intValue() : 500;
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("출고 주문 목록 직렬화 실패", e);
        }
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
    public EstimateDetailResponse detail(Long estimateId, AuthenticatedMember me) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        ownershipGuard.checkEstimateReadable(estimate, me);
        return toDetail(estimate);
    }

    /** 견적서 재료 — 상세 응답과 창고를 한 트랜잭션에서 읽는다 (S15P21A106-236). 소유권 확인은 상세 조회와 같다. */
    @Transactional(readOnly = true)
    public QuoteSource quoteSource(Long estimateId, AuthenticatedMember me) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        ownershipGuard.checkEstimateReadable(estimate, me);
        return new QuoteSource(toDetail(estimate), WarehouseResponse.from(estimate.getWarehouse()));
    }

    /**
     * 화면에 내보낼 1인칭 시점 키.
     *
     * <p>결과 도착 시점에 저장해 둔 값이 있으면 그것을 쓴다. 없으면 상단 키에서 다시 찾아 본다 —
     * 엣지가 mp4 를 하나씩 올리느라 상단만 올린 채 결과를 보고하면 그때 확인이 빈손이기 때문이다.
     * 여기서 저장하지 않는 이유는 조회가 읽기 전용 트랜잭션이라 써도 남지 않아서다.
     */
    private String fpvVideoKey(Estimate estimate) {
        String saved = estimate.getVerifyVideoFpvUrl();
        return saved != null ? saved : videoPresigner.deriveFpvKey(estimate.getVerifyVideoUrl());
    }

    private EstimateDetailResponse toDetail(Estimate estimate) {
        List<SimScenario> runs = scenarioRepository.findByEstimateIdOrderByAmrCountAsc(estimate.getId());
        List<EstimateDetailResponse.VerificationRun> verifications = verificationRuns(estimate.getId());
        return EstimateDetailResponse.of(estimate, runs,
                videoPresigner.sign(estimate.getVerifyVideoUrl()),
                videoPresigner.sign(fpvVideoKey(estimate)),
                verifyComparator.compare(estimate.getVerify(), recommendedRun(estimate, runs)),
                verifications, physicsLimit(verifications));
    }

    /**
     * 물리 검증 SSE 스냅샷 (S15P21A106-244). {@link VerifyEventStream} 이 구독·verify.done 양쪽에
     * 이걸로 보낸다 — 상세 조회와 같은 조립 로직을 두 번 쓰지 않으려고 여기 하나로 모은다.
     */
    @Transactional(readOnly = true)
    public EstimateEvents.VerificationsSnapshot verifySnapshot(Long estimateId) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        List<EstimateDetailResponse.VerificationRun> runs = verificationRuns(estimateId);
        return new EstimateEvents.VerificationsSnapshot(estimateId, estimate.getRecommendedCount(),
                physicsLimit(runs), runs);
    }

    /** 대수별 최신 시도 — 정렬이 대수 asc·시도 desc 라 각 대수의 첫 값이 최신 시도다. */
    private List<EstimateDetailResponse.VerificationRun> verificationRuns(Long estimateId) {
        List<EstimateVerification> all = verificationRepository.findByEstimateIdOrderByRobotCountAscAttemptDesc(estimateId);
        Map<Integer, EstimateVerification> latestByCount = new LinkedHashMap<>();
        for (EstimateVerification v : all) {
            latestByCount.putIfAbsent(v.getRobotCount(), v);
        }
        return latestByCount.values().stream().map(this::toVerificationRun).toList();
    }

    /** 후보 중 물리 판정이 PASS 인 가장 큰 대수 (명세 §D "물리 상한"). 없으면 null. */
    private Integer physicsLimit(List<EstimateDetailResponse.VerificationRun> runs) {
        return runs.stream()
                .filter(r -> PhysicsVerdict.Verdict.PASS.name().equals(r.verdict()))
                .map(EstimateDetailResponse.VerificationRun::nRobots)
                .max(Integer::compareTo)
                .orElse(null);
    }

    private EstimateDetailResponse.VerificationRun toVerificationRun(EstimateVerification v) {
        PhysicsMetrics physics = readPhysics(v.getPhysicsJson());
        PhysicsVerdict.Verdict verdict = PhysicsVerdict.of(v.getStatus(), physics);
        EstimateDetailResponse.VerificationRun.Slice slice = sliceView(v.getSliceMetaJson());
        String videoFpvKey = videoPresigner.deriveFpvKey(v.getVideoKey());
        return new EstimateDetailResponse.VerificationRun(
                v.getRobotCount(), v.getAttempt(), v.getStatus().name(), verdict.name(),
                v.getError(), v.getReason(),
                videoPresigner.sign(v.getVideoKey()), videoPresigner.sign(videoFpvKey),
                physics, slice, v.getRequestedAt(), v.getFinishedAt());
    }

    private EstimateDetailResponse.VerificationRun.Slice sliceView(String sliceMetaJson) {
        if (sliceMetaJson == null) {
            return null;
        }
        VerifySliceMeta meta = readSliceMeta(sliceMetaJson);
        return new EstimateDetailResponse.VerificationRun.Slice(meta.t0S(), meta.windowS(), meta.tasksDone());
    }

    private static SimScenario recommendedRun(Estimate estimate, List<SimScenario> runs) {
        Integer recommended = estimate.getRecommendedCount();
        if (recommended == null) {
            return null;
        }
        return runs.stream().filter(run -> recommended.equals(run.getAmrCount())).findFirst().orElse(null);
    }

    /**
     * 대수 하나의 앞 구간 재생 데이터 (S15P21A106-205).
     *
     * <p>저장할 때 맵과 궤적을 나눠 넣었으므로({@link #applyReplay}) 여기서 다시 합쳐 내보낸다.
     * 화면은 둘을 같이 받아야 그림을 그릴 수 있고, 나뉘어 있다는 건 저장 쪽 사정이다.
     *
     * <p>견적이 아직 안 끝났거나 그 대수 run 이 실패했으면 데이터가 없다 — 404 로 준다.
     * 진행 중인 것과 영원히 없는 것을 구분하지 않는 이유는, 프론트가 어느 쪽이든 "아직 못 본다"로
     * 같게 처리하기 때문이다.
     */
    @Transactional(readOnly = true)
    public String replay(Long estimateId, int amrCount, AuthenticatedMember me) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        ownershipGuard.checkEstimateReadable(estimate, me);

        SimScenario run = scenarioRepository.findByEstimateIdAndAmrCount(estimateId, amrCount)
                .orElseThrow(() -> new GlobalException(ErrorCode.ENTITY_NOT_FOUND));
        RunReplay stored = replayRepository.findById(run.getId())
                .orElseThrow(() -> new GlobalException(ErrorCode.ENTITY_NOT_FOUND));
        if (estimate.getReplaySceneJson() == null) {
            throw new GlobalException(ErrorCode.ENTITY_NOT_FOUND);
        }
        String trajectory = stored.getReplayJson().strip();
        String scene = estimate.getReplaySceneJson().strip();
        // 파싱하지 않고 문자열을 이어 붙인다 — 28대 12 MB 를 트리로 만들고 다시 쓰는 데 0.4~1.5 s 가 들었다 (S15P21A106-255)
        if (!isJsonObject(trajectory) || !isJsonObject(scene)) {
            log.error("리플레이 JSON 이 객체가 아닙니다: estimateId={}, amrCount={}", estimateId, amrCount);
            throw new GlobalException(ErrorCode.ENTITY_NOT_FOUND);
        }
        String body = trajectory.substring(0, trajectory.length() - 1).stripTrailing();
        String separator = body.endsWith("{") ? "" : ",";
        return body + separator + "\"" + REPLAY_SCENE + "\":" + scene + "}";
    }

    private static boolean isJsonObject(String json) {
        return json.length() >= 2 && json.charAt(0) == '{' && json.charAt(json.length() - 1) == '}';
    }

    /**
     * <b>소유권 검사가 없는</b> 조회. SSE 스트림이 스냅샷을 만들 때만 쓴다 — 그 경로는 컨트롤러가
     * {@link #checkAccess} 로 이미 걸렀다. 외부 요청을 직접 받는 자리에서는
     * {@link #detail(Long, AuthenticatedMember)} 를 써야 한다.
     */
    @Transactional(readOnly = true)
    public EstimateDetailResponse snapshot(Long estimateId) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        return toDetail(estimate);
    }

    @Transactional(readOnly = true)
    public Page<EstimateSummaryResponse> list(Pageable pageable, AuthenticatedMember me) {
        Page<Estimate> page = me.isAdmin()
                ? estimateRepository.findAllByOrderByCreatedAtDesc(pageable)
                : visibleTo(me, pageable);
        return page.map(EstimateSummaryResponse::from);
    }

    /** 내 견적. 체험 모드면 데모 회원의 견적도 함께 — 새로 가입한 사람은 자기 견적이 없다 (S15P21A106-283). */
    private Page<Estimate> visibleTo(AuthenticatedMember me, Pageable pageable) {
        return trialMode.showcaseOwnerEmail()
                .map(demoEmail -> estimateRepository.findByWarehouseMemberIdOrWarehouseMemberEmailOrderByCreatedAtDesc(
                        me.id(), demoEmail, pageable))
                .orElseGet(() -> estimateRepository.findByWarehouseMemberIdOrderByCreatedAtDesc(me.id(), pageable));
    }

    /** 견적 취소. 이미 큐에 들어간 run 의 결과가 와도 판정은 확정되지 않는다. */
    @Transactional
    public void cancel(Long estimateId, AuthenticatedMember me) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        ownershipGuard.checkEstimate(estimate, me);
        estimate.cancel();
        log.info("견적 취소: estimateId={}, status={}", estimateId, estimate.getStatus());
        if (estimate.isCancelled()) {
            eventPublisher.publishEvent(finishedEvent(estimate));
        }
    }

    /**
     * 견적을 지운다 — 대수별 run 과 주행 리플레이까지 함께 사라지고 되돌릴 수 없다 (S15P21A106-271).
     *
     * <p>진행 중이면 먼저 취소한다. 이미 큐에 들어간 run 의 결과는 뒤늦게 와도
     * {@link #applyResult} 가 "모르는 run" 으로 흘려보내므로 지워도 안전하다. 취소 이벤트를 함께
     * 내보내 열려 있던 진행 스트림이 닫히게 한다 — 안 그러면 화면이 없는 견적을 계속 기다린다.
     *
     * <p>리플레이는 DB 의 ON DELETE CASCADE 로 run 을 따라 지워진다(V9).
     */
    @Transactional
    public void delete(Long estimateId, AuthenticatedMember me) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        ownershipGuard.checkEstimate(estimate, me);

        estimate.cancel();
        if (estimate.isCancelled()) {
            eventPublisher.publishEvent(finishedEvent(estimate));
        }
        List<SimScenario> runs = scenarioRepository.findByEstimateIdOrderByAmrCountAsc(estimateId);
        scenarioRepository.deleteAll(runs);
        estimateRepository.delete(estimate);
        log.info("견적 삭제: estimateId={}, run={}개", estimateId, runs.size());
    }

    /**
     * 물리 검증(Isaac) 요청을 발행한다 (S15P21A106-244). 후보 대수는 {@code counts} 가 있으면 그대로,
     * 없으면 권장 대수 기준 n*−1·n*·n*+1 이다. 그중 DONE 이고 DES 피크 구간(궤적)이 있는 대수만
     * 실제로 검증한다 — 하나도 없으면(1단계 이전 옛 견적) 권장 대수 하나만 종전처럼 주문 목록으로
     * 폴백한다(둘 다 없을 순 없다 — 권장 대수 run 자체가 없으면 애초에 검증 불가로 거부한다).
     *
     * <p>{@code run_id} 는 이제 견적당 고정이 아니라 {@code verify_<estimateId>_n<K>_<attempt>} 다 —
     * 대수마다 따로 검증하고, 같은 대수를 다시 검증하려면 attempt 를 올려 host-orch 의 멱등 처리를
     * 비켜 간다(계약 §4·§5).
     *
     * @param counts 검증할 대수 목록. null 이면 권장 대수 기준 3개
     */
    @Transactional
    public void requestVerification(Long estimateId, AuthenticatedMember me, List<Integer> counts) {
        trialMode.rejectNewRequests();   // GPU 서버를 쓰지 않는다 (S15P21A106-283)
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        ownershipGuard.checkEstimate(estimate, me);
        Integer recommendedCount = estimate.getRecommendedCount();
        if (recommendedCount == null) {
            throw new GlobalException(ErrorCode.ESTIMATE_NOT_VERIFIABLE);
        }
        guardNoVerificationInProgress(estimateId);

        List<SliceCandidate> withTrajectory = candidateCounts(counts, recommendedCount).stream()
                .map(n -> sliceCandidate(estimateId, n))
                .filter(c -> c != null && c.slice().hasTrajectory())
                .toList();

        estimate.markVerifyRequested(LocalDateTime.now());
        if (withTrajectory.isEmpty()) {
            requestFallback(estimate, recommendedCount);
            return;
        }
        withTrajectory.forEach(candidate -> requestForCandidate(estimate, candidate));
    }

    /**
     * 진행 중인 회차가 있으면 새 요청을 거부한다. Isaac 은 노드당 한 건씩 약 10분을 문다 — 화면에서
     * 버튼을 잠가도 새로고침하면 상태가 풀려 다시 누를 수 있어서, 같은 검증이 큐에 두 번 쌓이는 것을
     * 여기서 막는다. 얼마나 오래됐는지는 보지 않는다 — 정리(TIMEOUT 스윕)는 후속 과제다.
     */
    private void guardNoVerificationInProgress(Long estimateId) {
        if (verificationRepository.existsByEstimateIdAndStatusIn(estimateId, VERIFY_PENDING)) {
            throw new GlobalException(ErrorCode.VERIFY_IN_PROGRESS);
        }
    }

    /** 후보 대수 목록 — override 가 있으면 그대로, 없으면 권장 대수 ±1. 0 이하·중복은 뺀다. */
    private List<Integer> candidateCounts(List<Integer> override, int recommendedCount) {
        List<Integer> base = override != null && !override.isEmpty()
                ? override
                : List.of(recommendedCount - 1, recommendedCount, recommendedCount + 1);
        return base.stream().distinct().filter(n -> n > 0).toList();
    }

    /** 대수 하나의 DONE run + 저장된 구간. 둘 중 하나라도 없으면 null(그 대수는 후보에서 빠진다). */
    private SliceCandidate sliceCandidate(Long estimateId, int amrCount) {
        return scenarioRepository.findByEstimateIdAndAmrCount(estimateId, amrCount)
                .filter(run -> run.getStatus() == RunStatus.DONE)
                .flatMap(run -> sliceRepository.findById(run.getId()).map(slice -> new SliceCandidate(run, slice)))
                .orElse(null);
    }

    private record SliceCandidate(SimScenario run, SimScenarioVerifySlice slice) {
    }

    /** 구간이 있는 대수 하나를 검증 큐에 발행 — 궤적을 싣는다(명세 §B). */
    private void requestForCandidate(Estimate estimate, SliceCandidate candidate) {
        int amrCount = candidate.run().getAmrCount();
        int attempt = nextAttempt(estimate.getId(), amrCount);
        String runId = verifyRunId(estimate.getId(), amrCount, attempt);
        VerifySliceMeta meta = readSliceMeta(candidate.slice().getMetaJson());
        long windowS = Math.round(meta.windowS());
        VerifyRequest.Scenario scenario = VerifyRequest.Scenario.ofTrajectory(
                FIXED_SEED, candidate.slice().getGzB64(), VerifyRequest.Slice.from(meta));

        verificationRepository.save(EstimateVerification.requested(
                estimate, amrCount, attempt, runId, candidate.slice().getMetaJson()));
        simulationService.publishVerify(new VerifyRequest(runId, amrCount, windowS,
                candidate.run().getRunId(), estimate.getId(), FIXED_SEED, scenario));
    }

    /**
     * 구간이 하나도 없는 견적(1단계 이전) 을 위한 폴백 — 권장 대수만, 종전처럼 견적 전체 주문 목록으로
     * 검증한다. run_id 형식은 새 형식({@code verify_<id>_n<K>_<attempt>}) 그대로 쓴다 — 대수별 행
     * 추적을 폴백에서도 그대로 누리기 위함이다.
     */
    private void requestFallback(Estimate estimate, int recommendedCount) {
        SimScenario run = scenarioRepository.findByEstimateIdAndAmrCount(estimate.getId(), recommendedCount)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_VERIFIABLE));
        int attempt = nextAttempt(estimate.getId(), recommendedCount);
        String runId = verifyRunId(estimate.getId(), recommendedCount, attempt);

        verificationRepository.save(EstimateVerification.requested(estimate, recommendedCount, attempt, runId, null));
        simulationService.publishVerify(new VerifyRequest(runId, recommendedCount, properties.verifyWindow().toSeconds(),
                run.getRunId(), estimate.getId(), FIXED_SEED, verifyScenario(estimate)));
    }

    private int nextAttempt(Long estimateId, int amrCount) {
        return verificationRepository.findFirstByEstimateIdAndRobotCountOrderByAttemptDesc(estimateId, amrCount)
                .map(v -> v.getAttempt() + 1)
                .orElse(1);
    }

    private String verifyRunId(Long estimateId, int amrCount, int attempt) {
        return "verify_%d_n%d_%d".formatted(estimateId, amrCount, attempt);
    }

    /**
     * 견적이 DES 스윕에 실제로 쓴 출고 주문 전체를 검증 시나리오로 싣는다(구간이 없는 옛 견적의 폴백).
     * 1단계 이전에 만들어진(주문 저장 전) 견적은 {@code outboundOrdersJson} 이 없으므로 시나리오 없이
     * 발행한다(하위 호환).
     */
    private VerifyRequest.Scenario verifyScenario(Estimate estimate) {
        String json = estimate.getOutboundOrdersJson();
        if (json == null) {
            return null;
        }
        List<SimulationRequest.Outbound> orders = readOutboundOrders(json);
        return orders.isEmpty() ? null : VerifyRequest.Scenario.ofOrders(FIXED_SEED, new VerifyRequest.Orders(null, orders));
    }

    /**
     * 저장된 출고 주문 목록의 건수. 결과가 올 때마다(대수당 1회, 견적당 최대 28회) 부르므로 700 KB 안팎의
     * JSON 을 객체로 풀지 않고 최상위 배열 원소만 스트리밍으로 센다.
     */
    private int countOutboundOrders(String json) {
        try (JsonParser parser = objectMapper.getFactory().createParser(json)) {
            if (parser.nextToken() != JsonToken.START_ARRAY) {
                return 0;
            }
            int count = 0;
            while (parser.nextToken() == JsonToken.START_OBJECT) {
                parser.skipChildren();
                count++;
            }
            return count;
        } catch (IOException e) {
            throw new IllegalStateException("출고 주문 목록 역직렬화 실패", e);
        }
    }

    private List<SimulationRequest.Outbound> readOutboundOrders(String json) {
        try {
            return objectMapper.readValue(json,
                    objectMapper.getTypeFactory().constructCollectionType(List.class, SimulationRequest.Outbound.class));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("출고 주문 목록 역직렬화 실패", e);
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
        if (STATUS_RUNNING.equals(response.status())) {
            run.markRunning();
            eventPublisher.publishEvent(new RunUpdated(run.getEstimate().getId(), EstimateDetailResponse.Run.from(run)));
            return;
        }

        if (isFailure(response)) {
            log.warn("시뮬 실패: runId={}, error={}", run.getRunId(), response.error());
            run.markFailed(response.error());
        } else {
            applyKpi(run, response.kpi());
            applyReplay(run, response.replay());
            applySlice(run, response.verifySlice());
        }
        eventPublisher.publishEvent(new RunUpdated(run.getEstimate().getId(), EstimateDetailResponse.Run.from(run)));

        finalizeIfComplete(run.getEstimate());
    }

    // ── 물리 검증 결과 반영 ──────────────────────────────────────────────────

    /**
     * 물리 검증(Isaac) 결과를 반영한다 (S15P21A106-244). {@code run_id} 로 대수별 회차를 찾을 수 있으면
     * (새 형식 {@code verify_<id>_n<K>_<attempt>}) 그 행을 갱신하고, 못 찾으면(244 이전에 발행된 옛
     * 형식 {@code verify_<id>}) 견적 단위 스냅샷만 갱신한다 — 두 경로 모두 성패와 무관하게 반영하고
     * 알린다. 모르는 견적 id 는 무시한다.
     */
    @Transactional
    public void applyVerifyResult(VerifyResultResponse response) {
        EstimateVerification verification = verificationRepository.findByRunId(response.runId()).orElse(null);
        if (verification != null) {
            applyVerificationResult(verification, response);
        } else {
            applyLegacyVerifyResult(response);
        }
    }

    /**
     * 대수별 회차 결과 반영. 그 대수가 견적의 권장 대수와 같으면 옛 화면·PDF 가 보는
     * {@code Estimate.verify} 스냅샷·영상도 함께 갱신한다.
     */
    private void applyVerificationResult(EstimateVerification verification, VerifyResultResponse response) {
        Estimate estimate = verification.getEstimate();
        VerifyRunStatus status = mapVerifyStatus(response.status());
        VerifyResultResponse.Artifacts artifacts = response.artifacts();
        String videoKey = artifacts != null ? artifacts.video() : null;
        String reason = response.verify() != null ? response.verify().reason() : null;
        verification.applyResult(status, response.error(), reason, videoKey,
                writeJsonOrNull(response.physics()), writeJsonOrNull(response.verify()));

        if (verification.getRobotCount().equals(estimate.getRecommendedCount())) {
            applyLegacySnapshot(estimate, response, videoKey, resolveFpv(videoKey, artifacts));
        }

        log.info("대수별 물리 검증 결과 반영: estimateId={}, nRobots={}, attempt={}, status={}",
                estimate.getId(), verification.getRobotCount(), verification.getAttempt(), status);
        Integer physicsLimit = physicsLimit(verificationRuns(estimate.getId()));
        eventPublisher.publishEvent(new EstimateEvents.VerificationUpdated(
                estimate.getId(), physicsLimit, toVerificationRun(verification)));
        if (!verificationRepository.existsByEstimateIdAndStatusIn(estimate.getId(), VERIFY_PENDING)) {
            eventPublisher.publishEvent(new EstimateEvents.VerificationsFinished(estimate.getId()));
        }
    }

    /** 244 이전에 발행된 옛 형식({@code verify_<estimateId>}) 결과 — 견적 단위 스냅샷만 갱신한다. */
    private void applyLegacyVerifyResult(VerifyResultResponse response) {
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
        VerifyResultResponse.Artifacts artifacts = response.artifacts();
        String video = artifacts != null ? artifacts.video() : null;
        String videoFpv = resolveFpv(video, artifacts);
        applyLegacySnapshot(estimate, response, video, videoFpv);
        log.info("물리 검증 결과 반영: estimateId={}, status={}, video={}, videoFpv={}",
                estimate.getId(), response.status(), video, videoFpv);
        eventPublisher.publishEvent(new EstimateVerified(
                estimate.getId(), response.status(), videoPresigner.sign(video),
                videoPresigner.sign(videoFpv), response.error()));
    }

    /**
     * 견적 단위 검증 스냅샷·영상 반영 — 옛(단일 검증) 화면·PDF 호환용. DB 에는 받은 값(과도기엔 공개
     * URL, 계약 정정 뒤엔 객체 키)을 그대로 두고, 서명은 조회·이벤트 시점에 한다.
     */
    private void applyLegacySnapshot(Estimate estimate, VerifyResultResponse response, String video, String videoFpv) {
        estimate.applyVerifyResult(toVerifySnapshot(response));
        // 상단이 없으면 1인칭만 남기지 않는다 — 화면이 기본으로 보여줄 것이 없어진다
        if (video != null) {
            estimate.applyVerifyVideo(video, videoFpv);
        }
    }

    /** 러너가 1인칭 키를 안 싣는 동안에는 상단 키에서 이름 규칙으로 찾아 본다 (S15P21A106-265). */
    private String resolveFpv(String video, VerifyResultResponse.Artifacts artifacts) {
        String videoFpv = artifacts != null ? artifacts.videoFpv() : null;
        return videoFpv != null ? videoFpv : videoPresigner.deriveFpvKey(video);
    }

    private VerifyRunStatus mapVerifyStatus(String status) {
        if ("done".equals(status)) {
            return VerifyRunStatus.DONE;
        }
        if ("running".equals(status)) {
            return VerifyRunStatus.RUNNING;
        }
        return VerifyRunStatus.FAILED;
    }

    /** 계약 §3 페이로드에서 견적에 남길 것만 뽑는다. verify·kpi 가 없는 옛 페이로드는 성패만 남는다. */
    private VerifySnapshot toVerifySnapshot(VerifyResultResponse response) {
        VerifyResultResponse.Verify verify = response.verify();
        SimulationResponse.Kpi kpi = response.kpi();
        VerifyResultResponse.Fms fms = verify == null ? null : verify.fms();
        return new VerifySnapshot(
                response.runId(), response.status(),
                verify == null ? null : verify.reason(), response.error(),
                verify == null ? null : verify.nRobots(),
                verify == null ? null : verify.robotsOnline(),
                verify == null ? null : verify.windowS(),
                warningsJson(fms),
                kpi == null ? null : kpi.throughputOrdersPerH(),
                kpi == null ? null : kpi.leadTimeP90S(),
                kpi == null ? null : kpi.conflictWaitRatio(),
                LocalDateTime.now());
    }

    private String warningsJson(VerifyResultResponse.Fms fms) {
        if (fms == null || fms.warnings() == null || fms.warnings().isNull()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(fms.warnings());
        } catch (JsonProcessingException e) {
            return fms.warnings().toString();
        }
    }

    /** {@code physics_json}·{@code verify_json} 저장용 — 실패해도 회차 갱신 자체를 막지 않는다. */
    private String writeJsonOrNull(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            log.warn("검증 결과 직렬화 실패: {}", e.toString());
            return null;
        }
    }

    private PhysicsMetrics readPhysics(String json) {
        if (json == null) {
            return null;
        }
        try {
            return objectMapper.readValue(json, PhysicsMetrics.class);
        } catch (JsonProcessingException e) {
            log.warn("물리 지표 역직렬화 실패: {}", e.toString());
            return null;
        }
    }

    /** 우리가 저장한 값이라 사실상 실패하지 않는다 — 나머지 objectMapper 역직렬화와 같은 스타일로 감싼다. */
    private VerifySliceMeta readSliceMeta(String json) {
        try {
            return objectMapper.readValue(json, VerifySliceMeta.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("구간 메타 역직렬화 실패", e);
        }
    }

    /**
     * 결과가 오지 않는 run 을 TIMEOUT 으로 정리한다.
     *
     * <p>이게 없으면 워커가 죽거나 발행 메시지가 유실될 때 그 run 이 QUEUED/RUNNING 에 갇히고, 견적이
     * 영원히 RUNNING 으로 남는다.
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
        run.markDone(throughputPercent(kpi), utilizationPercent(kpi), dailyOutbound(run, kpi), kpi.leadTimeP90S());
        run.applyKpiDetail(toKpiDetail(kpi));
        log.info("run 완료: runId={}, 처리율={}%, 가동률={}%",
                run.getRunId(), run.getThroughput(), run.getUtilization());
    }

    private RunKpiDetail toKpiDetail(SimulationResponse.Kpi kpi) {
        return new RunKpiDetail(kpi.ordersTotal(), kpi.ordersCompleted(), kpi.leadTimeMeanS(), kpi.queueTimeMeanS(),
                kpi.throughputOrdersPerH(), kpi.conflictWaitRatio(), kpi.distanceTotalM());
    }

    /**
     * 앞 구간 재생 데이터를 저장한다 (S15P21A106-205). 맵은 견적에, 궤적은 run 에 나눠 넣는다 —
     * 맵은 대수와 무관하게 같아서 run 마다 두면 같은 143 KB 가 대수만큼 중복된다.
     *
     * <p>실패해도 삼킨다. 리플레이는 곁다리라 이것 때문에 KPI 가 들어간 run 을 되돌릴 이유가 없다.
     */
    private void applyReplay(SimScenario run, JsonNode replay) {
        if (replay == null || replay.isNull()) {
            return;
        }
        try {
            JsonNode scene = replay.get(REPLAY_SCENE);
            if (scene != null && !scene.isNull()) {
                run.getEstimate().applyReplayScene(objectMapper.writeValueAsString(scene));
            }
            // 맵을 뺀 나머지(dt_s·model·seconds·robots·headings)가 run 별로 다른 부분이다
            ObjectNode trajectory = ((ObjectNode) replay).deepCopy();
            trajectory.remove(REPLAY_SCENE);
            replayRepository.save(new RunReplay(run.getId(), objectMapper.writeValueAsString(trajectory)));
        } catch (JsonProcessingException | ClassCastException e) {
            log.warn("리플레이 저장 실패 — run 은 그대로 둔다: runId={}, {}", run.getRunId(), e.toString());
        }
    }

    /**
     * DES 피크 구간(물리 검증용)을 저장한다 (S15P21A106-244). 구간을 못 만들었어도(gz_b64 없이 error
     * 만 있음) 화면이 사유를 보일 수 있도록 meta 는 저장한다 — run·replay·SSE 로는 절대 내보내지 않는다
     * (커도 300 KiB~440 KiB 라 브라우저로 새면 곤란하다).
     *
     * <p>실패해도 삼킨다. 구간은 곁다리라 이것 때문에 KPI 가 들어간 run 을 되돌릴 이유가 없다.
     */
    private void applySlice(SimScenario run, SimulationResponse.VerifySlice slice) {
        if (slice == null) {
            return;
        }
        try {
            String metaJson = objectMapper.writeValueAsString(slice.meta());
            sliceRepository.save(new SimScenarioVerifySlice(run.getId(), metaJson, slice.gzB64()));
        } catch (JsonProcessingException e) {
            log.warn("피크 구간 저장 실패 — run 은 그대로 둔다: runId={}, {}", run.getRunId(), e.toString());
        }
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
     * <p>시뮬은 백엔드가 생성한 하루치 주문 목록({@code outboundOrdersJson})을 그대로 받는다(-197). 그 목록이
     * 하루 전량이면 완료 건수가 곧 건/일이고, 실제 출고창이 horizon 보다 길어 앞부분만 잘려 갔으면
     * 하루 물량 ÷ 보낸 건수 배율로 되돌린다 (S15P21A106-214). 이전의 (실제 출고창 ÷ 시뮬 출고창) 배율은
     * 워커가 도착 간격으로 주문을 만들던 시절(-82)의 식이라 5시간 창고에서 ×1.25 로 부풀리고 있었다.
     *
     * <p>주문 목록이 없는 옛 견적(1단계 이전)은 환산 근거가 없으므로 실측값을 그대로 남긴다.
     */
    private Long dailyOutbound(SimScenario run, SimulationResponse.Kpi kpi) {
        Integer completed = kpi.ordersCompleted();
        if (completed == null) {
            return null;
        }
        Estimate estimate = run.getEstimate();
        String json = estimate.getOutboundOrdersJson();
        int sent = json == null ? 0 : countOutboundOrders(json);
        if (sent <= 0) {
            return completed.longValue();
        }
        long daily = outboundOrderCount(estimate.getWarehouse());
        return Math.round(completed * (double) daily / sent);
    }

    /**
     * SSE 구독 전 접근 검사. 스트림은 견적 id 만으로 여는 구조라, 이걸 안 하면 id 를 바꿔가며
     * 남의 견적 진행을 구독할 수 있다.
     */
    @Transactional(readOnly = true)
    public void checkAccess(Long estimateId, AuthenticatedMember me) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        ownershipGuard.checkEstimateReadable(estimate, me);
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
                estimate.getTargetThroughput(), estimate.getTargetUtilization(), estimate.getBudgetLimit(),
                properties.leadTimeP90LimitSeconds());

        EstimateVerdict verdict = evaluator.evaluate(results, goal);
        boolean anyFailed = results.size() != runs.size();
        estimate.complete(verdict.recommendedCount(), verdict.minimalCount(), verdict.kneeCount(),
                verdict.reasonCode(), anyFailed);

        log.info("견적 판정 확정: estimateId={}, 권장={}대, 최소={}대, 무릎={}대, 사유={}, 상태={}",
                estimate.getId(), verdict.recommendedCount(), verdict.minimalCount(), verdict.kneeCount(),
                verdict.reasonCode(), estimate.getStatus());
        eventPublisher.publishEvent(finishedEvent(estimate));
    }

    private EstimateFinished finishedEvent(Estimate estimate) {
        return new EstimateFinished(estimate.getId(), estimate.getStatus(), estimate.getRecommendedCount(),
                estimate.getMinimalCount(), estimate.getKneeCount(), estimate.getReasonCode());
    }

    private RunResult toRunResult(SimScenario run) {
        return new RunResult(
                run.getAmrCount(),
                run.getThroughput(),
                run.getUtilization(),
                run.getTotalCost() == null ? 0L : run.getTotalCost(),
                run.getLeadTimeP90());
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
