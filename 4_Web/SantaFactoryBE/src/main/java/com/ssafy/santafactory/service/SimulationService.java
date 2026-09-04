package com.ssafy.santafactory.service;

import com.ssafy.santafactory.client.SimulationClient;
import com.ssafy.santafactory.dto.simulation.SimulationAcceptedResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@RequiredArgsConstructor
public class SimulationService {

    private static final String STATUS_QUEUED = "queued";

    private final SimulationClient simulationClient;

    public SimulationAcceptedResponse requestSimulation(SimulationRequest request) {
        simulationClient.publish(request);
        log.info("시뮬레이션 요청 발행: runId={}", request.runId());
        return new SimulationAcceptedResponse(request.runId(), STATUS_QUEUED);
    }

    public void applyResult(SimulationResponse response) {
        if ("failed".equals(response.status())) {
            log.warn("시뮬레이션 실패: runId={}, error={}", response.runId(), response.error());
            return;
        }
        log.info("시뮬레이션 완료: runId={}, kpi={}", response.runId(), response.kpi());
    }
}
