package com.ssafy.santafactory.service;

import com.ssafy.santafactory.client.SimulationClient;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.dto.simulation.VerifyRequest;
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

    /**
     * run 식별자 규칙 — {@code {base}_n{대수}} (명세 §0).
     * 발행 전에 run 행을 만들어야 하는 호출자가 같은 규칙으로 id 를 미리 계산할 수 있게 꺼내 뒀다.
     */
    public static String runId(String baseRunId, int amrCount) {
        return "%s_n%d".formatted(baseRunId, amrCount);
    }

    public List<String> publishRuns(SimulationRequest base, List<Integer> amrCounts) {
        List<String> runIds = new ArrayList<>();
        for (int amrCount : amrCounts) {
            String runId = runId(base.runId(), amrCount);
            SimulationRequest.Amr amr = base.amr();
            simulationClient.publish(base.forRun(runId,
                    new SimulationRequest.Amr(amrCount, amr.speedEmpty(), amr.speedLoaded(), amr.consumption(),
                            amr.battery(), amr.chargeTime(), amr.chargeThreshold(), amr.capacity())));
            runIds.add(runId);
        }
        log.info("시뮬레이션 요청 발행: base={}, runs={}", base.runId(), runIds);
        return runIds;
    }

    public void publishVerify(VerifyRequest request) {
        simulationClient.publishVerify(request);
        log.info("물리 검증 요청 발행: runId={}, estimateId={}", request.runId(), request.estimateId());
    }

    public void applyResult(SimulationResponse response) {
        if ("failed".equals(response.status())) {
            log.warn("시뮬레이션 실패: runId={}, error={}", response.runId(), response.error());
            return;
        }
        log.info("시뮬레이션 완료: runId={}, kpi={}", response.runId(), response.kpi());
    }
}
