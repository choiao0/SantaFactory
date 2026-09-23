package com.ssafy.santafactory.service.estimate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateFinished;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunUpdated;
import java.time.LocalDateTime;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@ExtendWith(MockitoExtension.class)
class EstimateEventStreamTest {

    @Mock
    EstimateService estimateService;

    @InjectMocks
    EstimateEventStream stream;

    @Test
    void a_running_estimate_keeps_the_subscription_open_until_it_finishes() {
        when(estimateService.snapshot(77L)).thenReturn(detail(EstimateStatus.RUNNING));

        SseEmitter emitter = stream.subscribe(77L);

        assertThat(emitter).isNotNull();
        assertThat(stream.subscriberCount(77L)).isEqualTo(1);

        stream.onRunUpdated(new RunUpdated(77L, run(3, RunStatus.DONE)));
        assertThat(stream.subscriberCount(77L)).isEqualTo(1);

        stream.onEstimateFinished(new EstimateFinished(77L, EstimateStatus.DONE, 9, 9, 11, null));
        assertThat(stream.subscriberCount(77L)).isZero();
    }

    /** 롤링 배포에서 옛 파드가 내려갈 때 열린 SSE 가 graceful 대기 시간을 다 잡아먹지 않게 한다 (S15P21A106-258). */
    @Test
    void shutting_down_closes_every_open_subscription() {
        when(estimateService.snapshot(77L)).thenReturn(detail(EstimateStatus.RUNNING));
        when(estimateService.snapshot(78L)).thenReturn(detail(EstimateStatus.RUNNING));
        stream.subscribe(77L);
        stream.subscribe(78L);

        stream.closeAll();

        assertThat(stream.subscriberCount(77L)).isZero();
        assertThat(stream.subscriberCount(78L)).isZero();
    }

    /**
     * 스냅샷을 읽는 동안에도 워커 결과가 커밋될 수 있다. 그때 아직 구독자로 등록돼 있지 않으면 그
     * run 이벤트는 스냅샷에도 브로드캐스트에도 안 잡혀 사라지고, 화면에서 그 대수만 "대기" 로 굳었다가
     * 결과가 와서야 "완료" 로 튄다 (S15P21A106-263).
     */
    @Test
    void a_run_event_during_the_snapshot_read_still_reaches_the_subscriber() {
        AtomicInteger subscribersWhileReading = new AtomicInteger(-1);
        when(estimateService.snapshot(81L)).thenAnswer(invocation -> {
            subscribersWhileReading.set(stream.subscriberCount(81L));
            return detail(EstimateStatus.RUNNING);
        });

        stream.subscribe(81L);

        assertThat(subscribersWhileReading).hasValue(1);
    }

    @Test
    void a_finished_estimate_is_closed_right_after_the_snapshot() {
        when(estimateService.snapshot(78L)).thenReturn(detail(EstimateStatus.PARTIAL));

        stream.subscribe(78L);

        assertThat(stream.subscriberCount(78L)).isZero();
    }

    @Test
    void events_for_other_estimates_do_not_touch_a_subscription() {
        when(estimateService.snapshot(79L)).thenReturn(detail(EstimateStatus.RUNNING));
        stream.subscribe(79L);

        stream.onEstimateFinished(new EstimateFinished(80L, EstimateStatus.DONE, 5, 5, null, null));

        assertThat(stream.subscriberCount(79L)).isEqualTo(1);
    }

    private static EstimateDetailResponse detail(EstimateStatus status) {
        return new EstimateDetailResponse(77L, status, "iw.hub", 95.0, 80.0, 300_000_000L,
                null, null, null, null, LocalDateTime.now(), null, null, null, null, List.of(run(1, RunStatus.QUEUED)), null);
    }

    private static EstimateDetailResponse.Run run(int amrCount, RunStatus status) {
        return new EstimateDetailResponse.Run("est_77_n" + amrCount, amrCount, status,
                null, null, null, 15_500_000L * amrCount, null, null, null);
    }
}
