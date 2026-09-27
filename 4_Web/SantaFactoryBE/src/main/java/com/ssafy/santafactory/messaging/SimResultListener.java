package com.ssafy.santafactory.messaging;

import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.service.estimate.EstimateService;
import lombok.RequiredArgsConstructor;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class SimResultListener {

    private final EstimateService estimateService;

    @RabbitListener(queues = "${sim.result-queue:sim.result}")
    public void onResult(SimulationResponse response) {
        estimateService.applyResult(response);
    }
}
