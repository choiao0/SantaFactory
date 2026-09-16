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

        stream.onEstimateFinished(new EstimateFinished(77L, EstimateStatus.DONE, 9, 11, null));
        assertThat(stream.subscriberCount(77L)).isZero();
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

        stream.onEstimateFinished(new EstimateFinished(80L, EstimateStatus.DONE, 5, null, null));

        assertThat(stream.subscriberCount(79L)).isEqualTo(1);
    }

    private static EstimateDetailResponse detail(EstimateStatus status) {
        return new EstimateDetailResponse(77L, status, "iw.hub", 95.0, 80.0, 300_000_000L,
                null, null, null, LocalDateTime.now(), null, null, null, List.of(run(1, RunStatus.QUEUED)));
    }

    private static EstimateDetailResponse.Run run(int amrCount, RunStatus status) {
        return new EstimateDetailResponse.Run("est_77_n" + amrCount, amrCount, status,
                null, null, null, 15_500_000L * amrCount, null, null);
    }
}
