package com.ssafy.santafactory.service;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.global.config.SimProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@EnabledIfEnvironmentVariable(named = "RABBITMQ_HOST", matches = ".+")
class SimulationPublishIT {

    @Autowired
    SimulationService simulationService;

    @Autowired
    RabbitTemplate rabbitTemplate;

    @Autowired
    SimProperties simProperties;

    @Test
    void publishRuns_puts_one_message_per_amr_count_on_request_queue() {
        SimulationRequest base = new SimulationRequest(
                "est_it", 42L,
                new SimulationRequest.Warehouse(4, "01:00", "09:00", "13:00", "18:00", 480, 500),
                new SimulationRequest.Amr(0, 1.2, 1.0, 0.02, 100.0, 3600, 0.2, 8),
                List.of(new SimulationRequest.Inbound(5001L, 3L,
                        List.of(new SimulationRequest.Line(7L, "A2", 20)))),
                List.of(new SimulationRequest.Outbound(1001L, 0L,
                        List.of(new SimulationRequest.Line(7L, "A2", 1)))));

        simulationService.publishRuns(base, List.of(3, 5, 8));

        List<SimulationRequest> received = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            Object msg = rabbitTemplate.receiveAndConvert(simProperties.requestQueue(), 5000);
            assertThat(msg).isInstanceOf(SimulationRequest.class);
            received.add((SimulationRequest) msg);
        }

        assertThat(received).extracting(SimulationRequest::runId)
                .containsExactly("est_it_n3", "est_it_n5", "est_it_n8");
        assertThat(received).extracting(m -> m.amr().count()).containsExactly(3, 5, 8);
        assertThat(received.get(0).outbound()).isEqualTo(base.outbound());
    }
}
