package com.ssafy.santafactory.service.estimate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateVerified;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@ExtendWith(MockitoExtension.class)
class VerifyEventStreamTest {

    @Mock
    EstimateRepository estimateRepository;

    @Mock
    VerifyVideoPresigner videoPresigner;

    @InjectMocks
    VerifyEventStream stream;

    @Test
    void an_estimate_without_a_video_yet_keeps_the_subscription_open_until_a_result_arrives() {
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(Estimate.open(null, "iw.hub", 95.0, 80.0, 300_000_000L)));

        SseEmitter emitter = stream.subscribe(77L);

        assertThat(emitter).isNotNull();
        assertThat(stream.subscriberCount(77L)).isEqualTo(1);

        stream.onEstimateVerified(new EstimateVerified(77L, "done", "https://minio/videos/77.mp4", null, null));
        assertThat(stream.subscriberCount(77L)).isZero();
    }

    @Test
    void shutting_down_closes_every_open_subscription() {
        when(estimateRepository.findById(77L)).thenReturn(Optional.of(Estimate.open(null, "iw.hub", 95.0, 80.0, 300_000_000L)));
        stream.subscribe(77L);

        stream.closeAll();

        assertThat(stream.subscriberCount(77L)).isZero();
    }

    @Test
    void an_estimate_that_already_has_a_video_is_closed_right_after_the_snapshot() {
        Estimate estimate = Estimate.open(null, "iw.hub", 95.0, 80.0, 300_000_000L);
        estimate.applyVerifyVideo("verify_78/demo.mp4", null);
        when(estimateRepository.findById(78L)).thenReturn(Optional.of(estimate));

        stream.subscribe(78L);

        assertThat(stream.subscriberCount(78L)).isZero();
        verify(videoPresigner).sign("verify_78/demo.mp4");
    }

    @Test
    void events_for_other_estimates_do_not_touch_a_subscription() {
        when(estimateRepository.findById(79L)).thenReturn(Optional.of(Estimate.open(null, "iw.hub", 95.0, 80.0, 300_000_000L)));
        stream.subscribe(79L);

        stream.onEstimateVerified(new EstimateVerified(80L, "done", "https://minio/videos/80.mp4", null, null));

        assertThat(stream.subscriberCount(79L)).isEqualTo(1);
    }
}
