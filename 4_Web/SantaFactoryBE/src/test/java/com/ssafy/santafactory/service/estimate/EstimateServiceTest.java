package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.dto.simulation.VerifyRequest;
import com.ssafy.santafactory.dto.simulation.VerifyResultResponse;
import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.ReasonCode;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.simulation.RunKpiDetail;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.auth.OwnershipGuard;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.repository.SimScenarioRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import com.ssafy.santafactory.service.SimulationService;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunsQueued;
import com.ssafy.santafactory.service.estimate.ordergen.OutboundOrderGenerator;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.springframework.context.ApplicationEventPublisher;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.stream.IntStream;

import static com.ssafy.santafactory.support.TestPrincipals.ADMIN;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.within;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EstimateServiceTest {

    private static final EstimateProperties PROPS =
            new EstimateProperties(15_000_000L, 5_000_000L, 500_000L, 28, 6, 4, 1, Duration.ofMinutes(30), Duration.ofHours(6), "out", false, Duration.ofMinutes(10), 10, 10, 6, null);

    @Mock
    EstimateRepository estimateRepository;
    @Mock
    SimScenarioRepository scenarioRepository;
    @Mock
    WarehouseRepository warehouseRepository;
    @Mock
    SimulationService simulationService;

    @Mock
    ApplicationEventPublisher eventPublisher;
    @Mock
    OutboundOrderGenerator outboundOrderGenerator;
    @Mock
    VerifyVideoPresigner videoPresigner;

    private final CostCalculator costCalculator = new CostCalculator(PROPS);
    private final ObjectMapper objectMapper = new ObjectMapper();
    private EstimateService service;

 private EstimateService service() {
    if (service == null) {
        service = new EstimateService(
                estimateRepository,
                scenarioRepository,
                warehouseRepository,
                simulationService,
                costCalculator,
                new EstimateEvaluator(),
                PROPS,
                new OwnershipGuard(),
                eventPublisher,
                outboundOrderGenerator,
                objectMapper,
                videoPresigner,
                new VerifyComparator(new VerifyCompareProperties(0.10, 0.01))
        );
    }
    return service;
}

    // ── 생성 ─────────────────────────────────────────────────────────────────

    @Test
    void creates_runs_for_one_up_to_the_affordable_fleet_size() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);

        EstimateCreateResponse response = service().create(
                new EstimateCreateRequest(1L, null, null, null, null, null, null), ADMIN);

        // 예산 3억 ÷ 대당 1,550만 = 19대 + 여유 1 = 20대. 충전 존 상한 28 보다 작아 예산이 먼저 걸린다
        assertThat(response.estimateId()).isEqualTo(77L);
        assertThat(response.maxAmrCount()).isEqualTo(20);
        verify(scenarioRepository, times(20)).save(any());

        RunsQueued queued = queuedEvent();
        assertThat(queued.amrCounts()).containsExactlyElementsOf(IntStream.rangeClosed(1, 20).boxed().toList());
        assertThat(queued.request().runId()).isEqualTo("est_77");
    }

    @Test
    void generates_and_persists_the_same_outbound_orders_used_by_the_sweep() throws Exception {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);
        List<SimulationRequest.Outbound> orders = List.of(
                new SimulationRequest.Outbound(1L, 120L, List.of(new SimulationRequest.Line(5L, "A1", 2))));
        when(outboundOrderGenerator.generate(any(), anyLong(), anyInt(), anyLong())).thenReturn(orders);

        service().create(new EstimateCreateRequest(1L, null, null, null, null, null, null), ADMIN);

        // 대수별로 다시 생성하지 않고, 스윕 전체가 같은 리스트를 그대로 싣는다
        RunsQueued queued = queuedEvent();
        assertThat(queued.request().outbound()).isEqualTo(orders);

        // 그 리스트가 estimates.outbound_orders_json 에도 그대로 저장된다
        ArgumentCaptor<Estimate> saved = ArgumentCaptor.captor();
        verify(estimateRepository).save(saved.capture());
        String json = saved.getValue().getOutboundOrdersJson();
        assertThat(json).isNotNull();
        List<SimulationRequest.Outbound> roundTripped = objectMapper.readValue(json,
                objectMapper.getTypeFactory().constructCollectionType(List.class, SimulationRequest.Outbound.class));
        assertThat(roundTripped).isEqualTo(orders);
    }

    @Test
    void a_fleet_range_from_the_request_replaces_the_budget_based_sweep() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);

        EstimateCreateResponse response = service().create(
                new EstimateCreateRequest(1L, null, null, null, null, 3, 8), ADMIN);

        RunsQueued queued = queuedEvent();
        assertThat(queued.amrCounts()).containsExactly(3, 4, 5, 6, 7, 8);
        assertThat(response.maxAmrCount()).isEqualTo(8);
        verify(scenarioRepository, times(6)).save(any());
    }

    @Test
    void a_fleet_range_is_cut_at_the_charging_zone_cap() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);

        // 상한 28 을 넘는 29~35 는 발행하면 시뮬이 배치에서 죽으므로 잘라낸다
        EstimateCreateResponse response = service().create(
                new EstimateCreateRequest(1L, null, null, null, null, 25, 35), ADMIN);

        RunsQueued queued = queuedEvent();
        assertThat(queued.amrCounts()).containsExactly(25, 26, 27, 28);
        assertThat(response.maxAmrCount()).isEqualTo(28);
    }

    @Test
    void a_fleet_range_entirely_above_the_cap_is_rejected() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);

        assertThatThrownBy(() -> service().create(
                new EstimateCreateRequest(1L, null, null, null, null, 30, 40), ADMIN))
                .isInstanceOf(GlobalException.class)
                .extracting(e -> ((GlobalException) e).getErrorCode())
                .isEqualTo(ErrorCode.VALIDATION_ERROR);
        verify(eventPublisher, never()).publishEvent(any(RunsQueued.class));
    }

    @Test
    void run_rows_carry_the_queue_key_and_the_cost_of_their_fleet_size() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);

        service().create(new EstimateCreateRequest(1L, null, null, null, 50_000_000L, null, null), ADMIN);

        ArgumentCaptor<SimScenario> saved = ArgumentCaptor.captor();
        verify(scenarioRepository, times(4)).save(saved.capture());   // 5천만 / 1550만 = 3대 + 여유 1
        assertThat(saved.getAllValues()).extracting(SimScenario::getRunId)
                .containsExactly("est_77_n1", "est_77_n2", "est_77_n3", "est_77_n4");
        assertThat(saved.getAllValues()).extracting(SimScenario::getStatus)
                .containsOnly(RunStatus.QUEUED);
        assertThat(saved.getAllValues().get(3).getTotalCost()).isEqualTo(costCalculator.cost(4));
    }

    @Test
    void the_request_pins_the_fixed_time_run_and_keeps_the_real_arrival_rate() {
        givenWarehouse(1L);
        givenSavedEstimateId(77L);

        service().create(new EstimateCreateRequest(1L, null, null, null, null, null, null), ADMIN);

        RunsQueued queued = queuedEvent();
        SimulationRequest sent = queued.request();
        // 실행 시간을 명시하지 않으면 시뮬이 유한 주문 모드로 돌아 처리율이 전 대수 100 % 가 된다
        assertThat(sent.seed()).isEqualTo(101L);                          // 평가 시드, API 로 받지 않는다
        assertThat(sent.horizonS()).isEqualTo(21600L);                    // 6시간
        assertThat(sent.shifts()).isEqualTo("out");                        // 출고 전용 — 팀 결정(2026-09-11) 견적 부하 = 출고만 (S15P21A106-214)
        assertThat(sent.inboundGapS()).isEqualTo(48.0);                   // 600건 / 8시간
        assertThat(sent.outboundGapS()).isEqualTo(22.5);                  // 800건 / 5시간
        // 왕복당 토트 수. 안 보내면 시뮬 기본 1 로 돌아 처리율이 3~4배 비관적으로 나온다 (S15P21A106-218)
        assertThat(sent.amr().capacity()).isEqualTo(6);
    }

    @Test
    void a_shift_crossing_midnight_keeps_its_real_length() {
        // 야간 출고 22:00 → 06:00 (8시간). 같은 날짜로 저장돼 종료가 시작보다 앞선다
        Warehouse nightShift = mock(Warehouse.class);
        lenient().when(nightShift.getTargetThroughput()).thenReturn(95.0);
        lenient().when(nightShift.getTargetUtilization()).thenReturn(80.0);
        lenient().when(nightShift.getBudgetLimit()).thenReturn(300_000_000L);
        lenient().when(nightShift.getOutboundStart()).thenReturn(LocalDateTime.of(2026, 1, 1, 22, 0));
        lenient().when(nightShift.getOutboundEnd()).thenReturn(LocalDateTime.of(2026, 1, 1, 6, 0));
        lenient().when(nightShift.getOutboundAvg()).thenReturn(800L);
        when(warehouseRepository.findById(1L)).thenReturn(Optional.of(nightShift));
        givenSavedEstimateId(77L);

        service().create(new EstimateCreateRequest(1L, null, null, null, null, null, null), ADMIN);

        RunsQueued queued = queuedEvent();
        // 800건 / 8시간 = 36초. 24시간으로 폴백하면 108초가 되어 부하가 3배 과소 추정된다
        assertThat(queued.request().outboundGapS()).isEqualTo(36.0);
    }

    @Test
    void request_values_override_the_warehouse_defaults() {
        givenWarehouse(1L);
        ArgumentCaptor<Estimate> saved = ArgumentCaptor.captor();
        when(estimateRepository.save(saved.capture())).thenAnswer(call -> withId(call.getArgument(0), 77L));

        service().create(new EstimateCreateRequest(1L, "geek.p40", 88.0, 70.0, 100_000_000L, null, null), ADMIN);

        assertThat(saved.getValue().getAmrModel()).isEqualTo("geek.p40");
        assertThat(saved.getValue().getTargetThroughput()).isEqualTo(88.0);
        assertThat(saved.getValue().getTargetUtilization()).isEqualTo(70.0);
        assertThat(saved.getValue().getBudgetLimit()).isEqualTo(100_000_000L);
    }

    @Test
    void rejects_an_unknown_warehouse() {
        when(warehouseRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service().create(new EstimateCreateRequest(99L, null, null, null, null, null, null), ADMIN))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.WAREHOUSE_NOT_FOUND);
    }

    @Test
    void rejects_an_unknown_estimate_on_lookup() {
        when(estimateRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service().detail(99L, ADMIN))
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
        run.markDone(85.0, 95.0, 85L, null);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));

        service().applyResult(done(run.getRunId(), 100, 10, 0.1));   // 다른 값으로 재전달

        assertThat(run.getThroughput()).isEqualTo(85.0);             // 첫 결과가 유지된다
        assertThat(run.getUtilization()).isEqualTo(95.0);
        verify(scenarioRepository, never()).findByEstimateIdOrderByAmrCountAsc(any());
    }

    @Test
    void a_running_message_marks_the_run_running_and_notifies_without_finishing() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));

        service().applyResult(new SimulationResponse(run.getRunId(), "running", null, null, null));

        assertThat(run.getStatus()).isEqualTo(RunStatus.RUNNING);
        assertThat(run.getThroughput()).isNull();
        ArgumentCaptor<Object> event = ArgumentCaptor.captor();
        verify(eventPublisher).publishEvent(event.capture());
        assertThat(((EstimateEvents.RunUpdated) event.getValue()).run().status()).isEqualTo(RunStatus.RUNNING);
        verify(scenarioRepository, never()).findByEstimateIdOrderByAmrCountAsc(any());
    }

    @Test
    void a_running_message_after_the_result_is_ignored() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario run = run(estimate, 4);
        run.markDone(85.0, 95.0, 85L, null);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));

        service().applyResult(new SimulationResponse(run.getRunId(), "running", null, null, null));

        assertThat(run.getStatus()).isEqualTo(RunStatus.DONE);
        verify(eventPublisher, never()).publishEvent(any());
    }

    @Test
    void unpublished_runs_are_failed_and_the_estimate_is_finalized_from_the_rest() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario published = run(estimate, 2);
        published.markDone(100.0, 95.0, 100L, null);
        SimScenario third = run(estimate, 3);
        SimScenario fourth = run(estimate, 4);
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any()))
                .thenReturn(List.of(published, third, fourth));

        service().failUnpublished(1L, List.of(3, 4), "큐 연결 불가");

        assertThat(third.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(fourth.getStatus()).isEqualTo(RunStatus.FAILED);
        assertThat(third.getError()).isEqualTo("큐 연결 불가");
        assertThat(published.getStatus()).isEqualTo(RunStatus.DONE);
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.PARTIAL);
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
        twoAmr.markDone(60.0, 98.0, 60L, null);
        fourAmr.markDone(85.0, 95.0, 85L, null);
        when(scenarioRepository.findByRunId(sixAmr.getRunId())).thenReturn(Optional.of(sixAmr));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any()))
                .thenReturn(List.of(twoAmr, fourAmr, sixAmr));

        service().applyResult(done(sixAmr.getRunId(), 100, 95, 0.93));

        // 4·6대가 조건을 만족하고, 그중 효율 점수가 높은 6대가 권장이다
        // (4대 85 × 95 = 80.8, 6대 100 × 93 = 93.0)
        assertThat(estimate.getRecommendedCount()).isEqualTo(6);
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
        twoAmr.markDone(60.0, 98.0, 60L, null);
        fourAmr.markDone(85.0, 95.0, 85L, null);
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

        service().applyResult(new SimulationResponse(run.getRunId(), "done", null, null, null));

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

    // ── 건/일 환산 (S15P21A106-214) ───────────────────────────────────────────

    /**
     * 시뮬은 백엔드가 생성한 하루치 주문 목록을 그대로 받는다(-197). 목록이 하루 전량이면 완료 건수가 곧
     * 건/일이다 — 옛 배율(실제 출고창 ÷ 시뮬 출고창)은 간격 모드 잔재라 5시간 창고에서 ×1.25 로 부풀렸다.
     */
    @Test
    void reports_completed_orders_as_daily_volume_when_the_whole_day_was_sent() throws Exception {
        Estimate estimate = estimateWithOrders(4, 4);   // 하루 4건, 4건 전부 전송
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(run));

        service().applyResult(done(run.getRunId(), 4, 4, 0.9));

        assertThat(run.getOutbound()).isEqualTo(4L);
    }

    /** 실제 출고창이 horizon 보다 길어 목록 앞부분만 잘려 갔으면 하루 물량 ÷ 보낸 건수로 되돌린다. */
    @Test
    void scales_completed_orders_by_the_share_of_the_day_that_was_sent() throws Exception {
        Estimate estimate = estimateWithOrders(6, 4);   // 하루 6건 중 4건 전송
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(run));

        service().applyResult(done(run.getRunId(), 4, 2, 0.9));

        assertThat(run.getOutbound()).isEqualTo(3L);   // 2 × 6/4
    }

    /** 주문 목록이 없는 옛 견적(1단계 이전)은 환산 근거가 없으니 실측값을 그대로 둔다. */
    @Test
    void keeps_the_completed_count_for_an_estimate_without_a_stored_order_list() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(run));

        service().applyResult(done(run.getRunId(), 100, 90, 0.9));

        assertThat(run.getOutbound()).isEqualTo(90L);
    }

    // ── 물리 검증 결과 반영 ──────────────────────────────────────────────────

    @Test
    void ignores_a_verify_result_without_an_estimate_id() {
        assertThatCode(() -> service().applyVerifyResult(verifyDone("v1", null, "https://minio/v1.mp4")))
                .doesNotThrowAnyException();

        verify(estimateRepository, never()).findById(any());
    }

    @Test
    void ignores_a_verify_result_for_an_unknown_estimate() {
        when(estimateRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatCode(() -> service().applyVerifyResult(verifyDone("v1", 99L, "https://minio/v1.mp4")))
                .doesNotThrowAnyException();
    }

    @Test
    void stores_the_video_url_and_publishes_the_result() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));
        when(videoPresigner.sign("verify_77/v1.mp4"))
                .thenReturn("https://host/media/verify-videos/verify_77/v1.mp4?X-Amz-Signature=s");

        service().applyVerifyResult(verifyDone("v1", 77L, "verify_77/v1.mp4"));

        // DB 에는 받은 값 그대로, 브라우저로 나가는 이벤트에는 서명 URL
        assertThat(estimate.getVerifyVideoUrl()).isEqualTo("verify_77/v1.mp4");
        ArgumentCaptor<EstimateEvents.EstimateVerified> event = ArgumentCaptor.captor();
        verify(eventPublisher).publishEvent(event.capture());
        assertThat(event.getValue().estimateId()).isEqualTo(77L);
        assertThat(event.getValue().status()).isEqualTo("done");
        assertThat(event.getValue().videoUrl())
                .isEqualTo("https://host/media/verify-videos/verify_77/v1.mp4?X-Amz-Signature=s");
    }

    @Test
    void a_failed_verification_publishes_the_result_without_a_video_url() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));

        service().applyVerifyResult(new VerifyResultResponse("v1", "failed", "start timeout", 77L, null, null, null, null));

        assertThat(estimate.getVerifyVideoUrl()).isNull();
        ArgumentCaptor<EstimateEvents.EstimateVerified> event = ArgumentCaptor.captor();
        verify(eventPublisher).publishEvent(event.capture());
        assertThat(event.getValue().status()).isEqualTo("failed");
        assertThat(event.getValue().videoUrl()).isNull();
        assertThat(event.getValue().error()).isEqualTo("start timeout");
    }

    // ── 상세 지표·검증 결과 저장 (S15P21A106-236) ────────────────────────────

    @Test
    void apply_result_persists_kpi_detail_on_the_run() {
        Estimate estimate = estimate(85.0, 90.0, 1_000_000_000L);
        SimScenario run = run(estimate, 4);
        when(scenarioRepository.findByRunId(run.getRunId())).thenReturn(Optional.of(run));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(any())).thenReturn(List.of(run));

        service().applyResult(new SimulationResponse(run.getRunId(), "done", null, fullKpi(100, 96, 0.8), null));

        assertThat(run.getKpiDetail().getOrdersTotal()).isEqualTo(100);
        assertThat(run.getKpiDetail().getOrdersCompleted()).isEqualTo(96);
        assertThat(run.getKpiDetail().getLeadTimeMeanS()).isEqualTo(212.0);
        assertThat(run.getKpiDetail().getQueueTimeMeanS()).isEqualTo(48.0);
        assertThat(run.getKpiDetail().getThroughputOrdersPerH()).isEqualTo(159.0);
        assertThat(run.getKpiDetail().getConflictWaitRatio()).isEqualTo(0.068);
        assertThat(run.getKpiDetail().getDistanceTotalM()).isEqualTo(171_400L);
    }

    @Test
    void apply_verify_result_persists_snapshot_and_still_publishes_video_event() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));
        when(videoPresigner.sign("verify_77/v1.mp4")).thenReturn("https://host/signed");

        service().applyVerifyResult(verifyFull("verify_77", 77L, "verify_77/v1.mp4", VerifyShape.normal(14), fullKpi(30, 29, 0.7)));

        assertThat(estimate.getVerify().getRunId()).isEqualTo("verify_77");
        assertThat(estimate.getVerify().getStatus()).isEqualTo("done");
        assertThat(estimate.getVerify().getReason()).isEqualTo("window elapsed");
        assertThat(estimate.getVerify().getNRobots()).isEqualTo(14);
        assertThat(estimate.getVerify().getRobotsOnline()).isEqualTo(14);
        assertThat(estimate.getVerify().getWindowS()).isEqualTo(600);
        assertThat(estimate.getVerify().getWarningsJson()).isNull();
        assertThat(estimate.getVerify().getThroughputOrdersPerH()).isEqualTo(159.0);
        assertThat(estimate.getVerify().getLeadTimeP90S()).isEqualTo(384.0);
        assertThat(estimate.getVerify().getConflictWaitRatio()).isEqualTo(0.068);
        assertThat(estimate.getVerify().getVerifiedAt()).isNotNull();
        assertThat(estimate.getVerifyVideoUrl()).isEqualTo("verify_77/v1.mp4");
        ArgumentCaptor<EstimateEvents.EstimateVerified> event = ArgumentCaptor.captor();
        verify(eventPublisher).publishEvent(event.capture());
        assertThat(event.getValue().videoUrl()).isEqualTo("https://host/signed");
    }

    @Test
    void apply_verify_result_keeps_fms_warnings_as_json() throws Exception {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));
        JsonNode warnings = new ObjectMapper().readTree("[\"theta file missing\"]");

        service().applyVerifyResult(verifyFull("verify_77", 77L, null,
                new VerifyShape("window elapsed", 14, 14, warnings), fullKpi(30, 29, 0.7)));

        assertThat(estimate.getVerify().getWarningsJson()).isEqualTo("[\"theta file missing\"]");
    }

    @Test
    void detail_omits_verification_before_any_verify_result() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(77L)).thenReturn(List.of(run(estimate, 4)));

        EstimateDetailResponse detail = service().detail(77L, ADMIN);

        assertThat(detail.verification()).isNull();
        assertThat(detail.runs().get(0).kpi()).isNull();
    }

    @Test
    void detail_compares_verify_kpi_against_recommended_run() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        SimScenario two = run(estimate, 2);
        SimScenario four = run(estimate, 4);
        four.markDone(96.0, 80.0, 96L, 384.0);
        four.applyKpiDetail(new RunKpiDetail(100, 96, 212.0, 48.0, 159.0, 0.068, 171_400L));
        ReflectionTestUtils.setField(estimate, "createdAt", LocalDateTime.now());   // @PrePersist 가 없어 직접
        estimate.complete(4, null, null, false);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(77L)).thenReturn(List.of(two, four));

        // 검증: 시간당 152건, p90 414초(+7.8 %), 혼잡 0.081(+1.3 %p) → 혼잡이 기준을 넘는다
        service().applyVerifyResult(verifyFull("verify_77", 77L, null, VerifyShape.normal(4),
                new SimulationResponse.Kpi(30, 29, null, null, null, 230.0, 414.0, 50.0,
                        152.0, null, 0.72, 0.081, 30_000L, 0L)));
        EstimateDetailResponse detail = service().detail(77L, ADMIN);

        EstimateDetailResponse.Verification verification = detail.verification();
        assertThat(verification.notice()).isEqualTo(VerifyNoticeCode.SLOWER_AT_PEAK);
        assertThat(verification.comparison().throughputOrdersPerH().expected()).isEqualTo(159.0);
        assertThat(verification.comparison().throughputOrdersPerH().verified()).isEqualTo(152.0);
        assertThat(verification.comparison().throughputOrdersPerH().diff()).isEqualTo(-7.0);
        assertThat(verification.comparison().leadTimeP90S().expected()).isEqualTo(384.0);
        assertThat(verification.comparison().leadTimeP90S().diff()).isEqualTo(30.0);
        assertThat(verification.comparison().conflictWaitRatio().diff()).isCloseTo(0.013, within(1e-9));
        assertThat(detail.runs().get(1).kpi().throughputOrdersPerH()).isEqualTo(159.0);
    }

    @Test
    void verify_result_never_changes_the_verdict() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        estimate.complete(4, 6, null, false);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));

        service().applyVerifyResult(new VerifyResultResponse("verify_77", "failed", "runner NDEATH", 77L,
                null, null, null, null));

        assertThat(estimate.getRecommendedCount()).isEqualTo(4);
        assertThat(estimate.getKneeCount()).isEqualTo(6);
        assertThat(estimate.getStatus()).isEqualTo(EstimateStatus.DONE);
        assertThat(estimate.getVerify().getStatus()).isEqualTo("failed");
        assertThat(estimate.getVerify().getError()).isEqualTo("runner NDEATH");
    }

    // ── 물리 검증 요청 발행 ──────────────────────────────────────────────────

    @Test
    void rejects_verification_for_an_unknown_estimate() {
        when(estimateRepository.findById(99L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service().requestVerification(99L, ADMIN))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.ESTIMATE_NOT_FOUND);
        verify(simulationService, never()).publishVerify(any());
    }

    @Test
    void rejects_verification_when_there_is_no_recommended_count() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));

        assertThatThrownBy(() -> service().requestVerification(77L, ADMIN))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.ESTIMATE_NOT_VERIFIABLE);
        verify(simulationService, never()).publishVerify(any());
    }

    @Test
    void publishes_a_fixed_run_id_for_the_recommended_run() {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        estimate.complete(4, 6, null, false);
        SimScenario recommendedRun = run(estimate, 4);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));
        when(scenarioRepository.findByEstimateIdAndAmrCount(77L, 4)).thenReturn(Optional.of(recommendedRun));

        service().requestVerification(77L, ADMIN);

        ArgumentCaptor<VerifyRequest> request = ArgumentCaptor.captor();
        verify(simulationService).publishVerify(request.capture());
        assertThat(request.getValue().runId()).isEqualTo("verify_77");            // 견적당 고정 — 재요청해도 같은 id
        assertThat(request.getValue().nRobots()).isEqualTo(4);
        assertThat(request.getValue().windowS()).isEqualTo(600L);                 // EstimateProperties.verifyWindow 기본값
        assertThat(request.getValue().sourceRunId()).isEqualTo(recommendedRun.getRunId());
        assertThat(request.getValue().estimateId()).isEqualTo(77L);
        assertThat(request.getValue().seed()).isEqualTo(101L);
        assertThat(request.getValue().scenario()).isNull();   // outbound_orders_json 없는(1단계 이전) 견적 — 하위 호환
    }

    @Test
    void ships_the_full_outbound_order_list_as_the_verify_scenario() throws Exception {
        Estimate estimate = withId(estimate(85.0, 90.0, 1_000_000_000L), 77L);
        estimate.complete(4, 6, null, false);
        List<SimulationRequest.Outbound> orders = List.of(
                new SimulationRequest.Outbound(1L, 120L, List.of(new SimulationRequest.Line(5L, "A1", 2))));
        estimate.applyOutboundOrders(objectMapper.writeValueAsString(orders));
        SimScenario recommendedRun = run(estimate, 4);
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(estimate));
        when(scenarioRepository.findByEstimateIdAndAmrCount(77L, 4)).thenReturn(Optional.of(recommendedRun));

        service().requestVerification(77L, ADMIN);

        ArgumentCaptor<VerifyRequest> request = ArgumentCaptor.captor();
        verify(simulationService).publishVerify(request.capture());
        assertThat(request.getValue().scenario().seed()).isEqualTo(101L);
        assertThat(request.getValue().scenario().orders().outbound()).isEqualTo(orders);
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
        twoAmr.markDone(60.0, 98.0, 60L, null);
        fourAmr.markDone(85.0, 95.0, 85L, null);
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
        lenient().when(outboundOrderGenerator.generate(any(), anyLong(), anyInt(), anyLong())).thenReturn(List.of());
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

    /** 하루 출고 {@code dailyOutbound} 건인 창고(품고 시간대 13~18시)의 견적에 {@code sentOrders} 건의 주문 목록을 붙인다. */
    private Estimate estimateWithOrders(long dailyOutbound, int sentOrders) throws Exception {
        Warehouse warehouse = mock(Warehouse.class);
        lenient().when(warehouse.getOutboundAvg()).thenReturn(dailyOutbound);
        lenient().when(warehouse.getOutboundStart()).thenReturn(LocalDateTime.of(2026, 1, 1, 13, 0));
        lenient().when(warehouse.getOutboundEnd()).thenReturn(LocalDateTime.of(2026, 1, 1, 18, 0));
        Estimate estimate = Estimate.open(warehouse, "iw.hub", 85.0, 90.0, 1_000_000_000L);
        List<SimulationRequest.Outbound> orders = IntStream.rangeClosed(1, sentOrders)
                .mapToObj(i -> new SimulationRequest.Outbound((long) i, 60L * i, List.of(new SimulationRequest.Line(5L, "A1", 1))))
                .toList();
        estimate.applyOutboundOrders(objectMapper.writeValueAsString(orders));
        return estimate;
    }

    private SimScenario run(Estimate estimate, int amrCount) {
        return SimScenario.queued(estimate, "est_1_n" + amrCount, amrCount, costCalculator.cost(amrCount));
    }

    /** 생성이 커밋 뒤 발행용으로 남긴 이벤트. 발행 자체는 {@link SimRequestDispatcher} 가 한다. */
    private RunsQueued queuedEvent() {
        ArgumentCaptor<Object> events = ArgumentCaptor.captor();
        verify(eventPublisher, atLeastOnce()).publishEvent(events.capture());
        return events.getAllValues().stream()
                .filter(RunsQueued.class::isInstance).map(RunsQueued.class::cast)
                .findFirst().orElseThrow();
    }

    private SimulationResponse done(String runId, int ordersTotal, int ordersCompleted, double amrUtilization) {
        SimulationResponse.Kpi kpi = new SimulationResponse.Kpi(
                ordersTotal, ordersCompleted, null, null,
                null, null, null, null,
                null, null,
                amrUtilization, null, null, null);
        return new SimulationResponse(runId, "done", null, kpi, null);
    }

    private SimulationResponse failed(String runId, String error) {
        return new SimulationResponse(runId, "failed", error, null, null);
    }

    /** 리플레이 한 벌 — scene(맵)과 궤적이 함께 온다. 실제 워커 응답과 같은 모양이다. */
    private SimulationResponse doneWithReplay(String runId, String sceneMark) throws Exception {
        SimulationResponse plain = done(runId, 10, 10, 0.5);
        String replay = """
                {"dt_s":0.5,"model":"heading","seconds":600.0,
                 "robots":{"0":[[0.0,1.0,2.0]]},"headings":{"0":[0.0]},
                 "scene":{"meta":{"map":"%s"}}}
                """.formatted(sceneMark);
        return new SimulationResponse(runId, plain.status(), null, plain.kpi(),
                new ObjectMapper().readTree(replay));
    }

    // ── 리플레이 (S15P21A106-205) ────────────────────────────────────────────

    @Test
    void replay_is_split_so_the_map_is_stored_once_per_estimate() throws Exception {
        Estimate estimate = withId(estimate(90.0, 80.0, 300_000_000L), 1L);
        SimScenario three = run(estimate, 3);
        SimScenario five = run(estimate, 5);
        when(scenarioRepository.findByRunId("est_1_n3")).thenReturn(Optional.of(three));
        when(scenarioRepository.findByRunId("est_1_n5")).thenReturn(Optional.of(five));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(1L)).thenReturn(List.of(three, five));

        service().applyResult(doneWithReplay("est_1_n3", "wallA"));
        service().applyResult(doneWithReplay("est_1_n5", "다른맵"));

        // 궤적은 run 마다, 맵은 견적에 한 벌 — 그래야 143 KB 짜리가 대수만큼 중복되지 않는다
        assertThat(three.getReplayJson()).contains("robots").doesNotContain("scene");
        assertThat(five.getReplayJson()).contains("robots").doesNotContain("scene");
        // 먼저 온 것만 남는다. 어차피 같은 맵이라 덮어쓰면 같은 값을 다시 쓰는 UPDATE 가 된다
        assertThat(estimate.getReplaySceneJson()).contains("wallA").doesNotContain("다른맵");
    }

    @Test
    void replay_recombines_the_map_and_the_trajectory() throws Exception {
        Estimate estimate = withId(estimate(90.0, 80.0, 300_000_000L), 1L);
        SimScenario three = run(estimate, 3);
        when(scenarioRepository.findByRunId("est_1_n3")).thenReturn(Optional.of(three));
        when(scenarioRepository.findByEstimateIdOrderByAmrCountAsc(1L)).thenReturn(List.of(three));
        service().applyResult(doneWithReplay("est_1_n3", "wallA"));

        when(estimateRepository.findById(1L)).thenReturn(Optional.of(estimate));
        when(scenarioRepository.findByEstimateIdAndAmrCount(1L, 3)).thenReturn(Optional.of(three));

        JsonNode replay = service().replay(1L, 3, ADMIN);

        // 나눠 저장한 것은 저장 쪽 사정이다 — 화면은 둘을 같이 받아야 그림을 그린다
        assertThat(replay.get("scene").get("meta").get("map").asText()).isEqualTo("wallA");
        assertThat(replay.get("robots").has("0")).isTrue();
        assertThat(replay.get("seconds").asDouble()).isEqualTo(600.0);
    }

    @Test
    void replay_is_404_when_the_run_has_none() {
        Estimate estimate = withId(estimate(90.0, 80.0, 300_000_000L), 1L);
        SimScenario three = run(estimate, 3);
        when(estimateRepository.findById(1L)).thenReturn(Optional.of(estimate));
        when(scenarioRepository.findByEstimateIdAndAmrCount(1L, 3)).thenReturn(Optional.of(three));

        // 아직 결과가 없는 것과 영원히 없는 것을 구분하지 않는다 — 프론트는 어느 쪽이든 같게 다룬다
        assertThatThrownBy(() -> service().replay(1L, 3, ADMIN))
                .isInstanceOf(GlobalException.class);
    }

    private VerifyResultResponse verifyDone(String runId, Long estimateId, String videoUrl) {
        return new VerifyResultResponse(runId, "done", null, estimateId, null,
                new VerifyResultResponse.Artifacts(videoUrl), null, null);
    }

    /** 검증 런의 모양 — 종료 사유, 로봇 수, 가동 수, fms 경고. */
    private record VerifyShape(String reason, int nRobots, int robotsOnline, JsonNode warnings) {
        static VerifyShape normal(int robots) {
            return new VerifyShape("window elapsed", robots, robots, null);
        }
    }

    /** 계약 §3 전체 모양 — verify 블록과 kpi 까지 온 결과. */
    private VerifyResultResponse verifyFull(String runId, Long estimateId, String videoUrl, VerifyShape shape,
                                            SimulationResponse.Kpi kpi) {
        return new VerifyResultResponse(runId, "done", null, estimateId,
                "est_%d_n%d".formatted(estimateId, shape.nRobots()),
                videoUrl == null ? null : new VerifyResultResponse.Artifacts(videoUrl),
                new VerifyResultResponse.Verify(shape.nRobots(), shape.robotsOnline(), 600, shape.reason(),
                        new VerifyResultResponse.Fms("done", null, shape.warnings())),
                kpi);
    }

    /** 14개 키가 전부 채워진 kpi. 시간당 159건 · 평균 212초 · p90 384초 · 대기 48초 · 혼잡 6.8 % · 171.4 km. */
    private SimulationResponse.Kpi fullKpi(int ordersTotal, int ordersCompleted, double amrUtilization) {
        return new SimulationResponse.Kpi(
                ordersTotal, ordersCompleted, 0, 0,
                21_600L, 212.0, 384.0, 48.0,
                159.0, 167.0,
                amrUtilization, 0.068, 171_400L, 0L);
    }
}
