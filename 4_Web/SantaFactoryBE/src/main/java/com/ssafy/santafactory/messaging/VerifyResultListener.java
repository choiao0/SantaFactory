package com.ssafy.santafactory.messaging;

import com.ssafy.santafactory.dto.simulation.VerifyResultResponse;
import com.ssafy.santafactory.service.estimate.EstimateService;
import lombok.RequiredArgsConstructor;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class VerifyResultListener {

    private final EstimateService estimateService;

    @RabbitListener(queues = "${sim.verify-result-queue:sim.verify.result}")
    public void onResult(VerifyResultResponse response) {
        estimateService.applyVerifyResult(response);
    }
}
