package com.ssafy.santafactory.client;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.VerifyRequest;
import com.ssafy.santafactory.global.config.SimProperties;
import com.ssafy.santafactory.support.TrialFixtures;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.amqp.AmqpConnectException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

@ExtendWith(MockitoExtension.class)
class SimulationClientTest {

    @Mock
    RabbitTemplate rabbitTemplate;

    private final SimProperties props = new SimProperties("sim.request", "sim.result", "sim.verify.request", "sim.verify.result");

    private final SimulationRequest request = new SimulationRequest(
            "est_77_n3", 42L, 21600L, "in,in,out,out,out,out", 48.0, 22.5,
            new SimulationRequest.Warehouse(4, "01:00", "09:00", "13:00", "18:00", 480, 500),
            new SimulationRequest.Amr(3, 1.2, 1.0, 0.02, 100.0, 3600, 0.2, 8),
            List.of(), List.of(), null);

    @Test
    void publish_sends_request_to_request_queue() {
        new SimulationClient(rabbitTemplate, props, TrialFixtures.off()).publish(request);

        verify(rabbitTemplate).convertAndSend(eq("sim.request"), eq(request));
    }

    @Test
    void publish_maps_amqp_failure_to_SIM503() {
        doThrow(new AmqpConnectException(new RuntimeException("refused")))
                .when(rabbitTemplate).convertAndSend(eq("sim.request"), any(Object.class));

        assertThatThrownBy(() -> new SimulationClient(rabbitTemplate, props, TrialFixtures.off()).publish(request))
                .isInstanceOf(GlobalException.class)
                .satisfies(e -> assertThat(((GlobalException) e).getErrorCode())
                        .isEqualTo(ErrorCode.SIM_QUEUE_UNAVAILABLE));
    }

    /** 서비스 입구에서 막지만, 어떤 경로로 와도 큐에는 넣지 않는 마지막 둑 (S15P21A106-283). */
    @Test
    void trial_mode_never_reaches_either_queue() {
        SimulationClient client = new SimulationClient(rabbitTemplate, props, TrialFixtures.on());
        VerifyRequest verify = new VerifyRequest("verify_77_n4_1", 4, 600L, "est_77_n4", 77L, 101L, null);

        assertThatThrownBy(() -> client.publish(request))
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.TRIAL_READ_ONLY);
        assertThatThrownBy(() -> client.publishVerify(verify))
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.TRIAL_READ_ONLY);
        verifyNoInteractions(rabbitTemplate);
    }
}
