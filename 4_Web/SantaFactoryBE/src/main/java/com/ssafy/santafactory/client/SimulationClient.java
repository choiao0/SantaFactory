package com.ssafy.santafactory.client;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.VerifyRequest;
import com.ssafy.santafactory.global.auth.TrialMode;
import com.ssafy.santafactory.global.config.SimProperties;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class SimulationClient {

    private final RabbitTemplate rabbitTemplate;
    private final SimProperties simProperties;
    private final TrialMode trialMode;

    public void publish(SimulationRequest request) {
        // 서비스 입구에서 이미 막지만, 어떤 경로로 와도 워커 큐에는 넣지 않는 마지막 둑 (S15P21A106-283)
        trialMode.rejectNewRequests();
        try {
            rabbitTemplate.convertAndSend(simProperties.requestQueue(), request);
        } catch (AmqpException e) {
            log.error("시뮬레이션 요청 발행 실패: runId={}, queue={}", request.runId(), simProperties.requestQueue(), e);
            throw new GlobalException(ErrorCode.SIM_QUEUE_UNAVAILABLE);
        }
    }

    public void publishVerify(VerifyRequest request) {
        trialMode.rejectNewRequests();
        try {
            rabbitTemplate.convertAndSend(simProperties.verifyRequestQueue(), request);
        } catch (AmqpException e) {
            log.error("물리 검증 요청 발행 실패: runId={}, queue={}", request.runId(), simProperties.verifyRequestQueue(), e);
            throw new GlobalException(ErrorCode.SIM_QUEUE_UNAVAILABLE);
        }
    }
}
