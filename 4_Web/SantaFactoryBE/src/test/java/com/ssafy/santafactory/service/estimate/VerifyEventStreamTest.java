package com.ssafy.santafactory.service.estimate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.VerificationRun;
import com.ssafy.santafactory.service.estimate.EstimateEvents.VerificationUpdated;
import com.ssafy.santafactory.service.estimate.EstimateEvents.VerificationsFinished;
import com.ssafy.santafactory.service.estimate.EstimateEvents.VerificationsSnapshot;
import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * (S15P21A106-244) 여러 대수를 동시에 검증하므로 첫 결과가 왔다고 연결을 끊지 않는다는 점을 확인한다 —
 * 옛 단일 검증 채널({@code onEstimateVerified})과 가장 다른 지점이다.
 */
@ExtendWith(MockitoExtension.class)
class VerifyEventStreamTest {

    @Mock
    EstimateService estimateService;

    @InjectMocks
    VerifyEventStream stream;

    @Test
    void an_estimate_never_verified_keeps_the_subscription_open() {
        when(estimateService.verifySnapshot(77L)).thenReturn(snapshot(77L, List.of()));

        SseEmitter emitter = stream.subscribe(77L);

        assertThat(emitter).isNotNull();
        assertThat(stream.subscriberCount(77L)).isEqualTo(1);
    }

    @Test
    void an_estimate_whose_verifications_are_all_finished_is_closed_right_after_the_snapshot() {
        when(estimateService.verifySnapshot(78L)).thenReturn(
                snapshot(78L, List.of(run(10, "DONE", "PASS"))));

        stream.subscribe(78L);

        assertThat(stream.subscriberCount(78L)).isZero();
    }

    /**
     * (S15P21A106-279) 다 끝난 견적을 다시 열면 snapshot 만 보내고 닫았다 — 화면은 verify.done 에서만 닫으므로
     * 브라우저 EventSource 가 3초마다 재접속했고, 매번 새로 서명한 영상 URL 이 와서 재생 중인 영상이 처음으로 돌아갔다.
     */
    @Test
    void reopening_a_finished_estimate_sends_done_so_the_browser_does_not_reconnect() throws Exception {
        SseEmitter emitter = mock(SseEmitter.class);
        VerifyEventStream spied = spy(stream);
        doReturn(emitter).when(spied).newEmitter();
        when(estimateService.verifySnapshot(78L)).thenReturn(
                snapshot(78L, List.of(run(10, "DONE", "WARN"), run(11, "FAILED", "FAIL"))));

        spied.subscribe(78L);

        assertThat(sentEventNames(emitter)).containsExactly("snapshot", "verify.done");
        verify(emitter).complete();
    }

    @Test
    void a_subscription_still_waiting_for_results_gets_only_the_snapshot() throws Exception {
        SseEmitter emitter = mock(SseEmitter.class);
        VerifyEventStream spied = spy(stream);
        doReturn(emitter).when(spied).newEmitter();
        when(estimateService.verifySnapshot(79L)).thenReturn(
                snapshot(79L, List.of(run(9, "DONE", "PASS"), run(10, "RUNNING", "NA"))));

        spied.subscribe(79L);

        assertThat(sentEventNames(emitter)).containsExactly("snapshot");
        verify(emitter, never()).complete();
    }

    @Test
    void an_estimate_with_one_pending_candidate_keeps_the_subscription_open() {
        when(estimateService.verifySnapshot(79L)).thenReturn(
                snapshot(79L, List.of(run(9, "DONE", "PASS"), run(10, "PENDING", "NA"))));

        stream.subscribe(79L);

        assertThat(stream.subscriberCount(79L)).isEqualTo(1);
    }

    /** 후보 하나의 결과가 와도 나머지가 진행 중일 수 있어 연결을 끊지 않는다 — verify.done 과의 핵심 차이. */
    @Test
    void a_verification_update_is_broadcast_without_closing_the_subscription() {
        when(estimateService.verifySnapshot(80L)).thenReturn(snapshot(80L, List.of()));
        stream.subscribe(80L);

        stream.onVerificationUpdated(new VerificationUpdated(80L, null, run(10, "DONE", "WARN")));

        assertThat(stream.subscriberCount(80L)).isEqualTo(1);
    }

    @Test
    void all_verifications_finished_broadcasts_done_and_closes_the_subscription() {
        when(estimateService.verifySnapshot(81L)).thenReturn(snapshot(81L, List.of()));
        stream.subscribe(81L);
        when(estimateService.verifySnapshot(81L)).thenReturn(
                snapshot(81L, List.of(run(9, "DONE", "PASS"), run(10, "DONE", "PASS"))));

        stream.onVerificationsFinished(new VerificationsFinished(81L));

        assertThat(stream.subscriberCount(81L)).isZero();
    }

    @Test
    void shutting_down_closes_every_open_subscription() {
        when(estimateService.verifySnapshot(77L)).thenReturn(snapshot(77L, List.of()));
        stream.subscribe(77L);

        stream.closeAll();

        assertThat(stream.subscriberCount(77L)).isZero();
    }

    @Test
    void events_for_other_estimates_do_not_touch_a_subscription() {
        when(estimateService.verifySnapshot(79L)).thenReturn(snapshot(79L, List.of()));
        stream.subscribe(79L);

        stream.onVerificationsFinished(new VerificationsFinished(80L));

        assertThat(stream.subscriberCount(79L)).isEqualTo(1);
    }

    /** 보낸 SSE 이벤트 이름 순서 — 빌더가 만드는 {@code event:<이름>} 줄에서 읽는다. */
    private List<String> sentEventNames(SseEmitter emitter) throws Exception {
        ArgumentCaptor<SseEmitter.SseEventBuilder> sent = ArgumentCaptor.forClass(SseEmitter.SseEventBuilder.class);
        verify(emitter, atLeastOnce()).send(sent.capture());
        return sent.getAllValues().stream()
                .map(b -> b.build().stream().map(d -> String.valueOf(d.getData())).collect(Collectors.joining()))
                .map(text -> text.lines().filter(l -> l.startsWith("event:")).findFirst().orElse("event:?").substring(6))
                .toList();
    }

    private VerificationsSnapshot snapshot(Long estimateId, List<VerificationRun> runs) {
        return new VerificationsSnapshot(estimateId, 10, null, runs);
    }

    private VerificationRun run(int nRobots, String status, String verdict) {
        return new VerificationRun(nRobots, 1, status, verdict, null, null, null, null, null, null,
                LocalDateTime.now(), status.equals("DONE") || status.equals("FAILED") ? LocalDateTime.now() : null);
    }
}
