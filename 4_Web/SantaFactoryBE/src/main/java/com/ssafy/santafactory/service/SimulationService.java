package com.ssafy.santafactory.service;

import com.ssafy.santafactory.client.SimulationClient;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class SimulationService {

    private final SimulationClient simulationClient;

    public List<String> publishRuns(SimulationRequest base, List<Integer> amrCounts) {
        List<String> runIds = new ArrayList<>();
        for (int amrCount : amrCounts) {
            String runId = "%s_n%d".formatted(base.runId(), amrCount);
            SimulationRequest.Amr amr = base.amr();
            simulationClient.publish(new SimulationRequest(
                    runId,
                    base.seed(),
                    base.warehouse(),
                    new SimulationRequest.Amr(amrCount, amr.speedEmpty(), amr.speedLoaded(), amr.consumption(),
                            amr.battery(), amr.chargeTime(), amr.chargeThreshold(), amr.capacity()),
                    base.inbound(),
                    base.outbound()));
            runIds.add(runId);
        }
        log.info("시뮬레이션 요청 발행: base={}, runs={}", base.runId(), runIds);
        return runIds;
    }

    public void applyResult(SimulationResponse response) {
        if ("failed".equals(response.status())) {
            log.warn("시뮬레이션 실패: runId={}, error={}", response.runId(), response.error());
            return;
        }
        log.info("시뮬레이션 완료: runId={}, kpi={}", response.runId(), response.kpi());
    }
}
