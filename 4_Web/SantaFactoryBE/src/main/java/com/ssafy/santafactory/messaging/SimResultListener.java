package com.ssafy.santafactory.messaging;

import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.service.SimulationService;
import lombok.RequiredArgsConstructor;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class SimResultListener {

    private final SimulationService simulationService;

    @RabbitListener(queues = "${sim.result-queue:sim.result}")
    public void onResult(SimulationResponse response) {
        simulationService.applyResult(response);
    }
}
