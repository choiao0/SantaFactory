package com.ssafy.santafactory.service;

import com.ssafy.santafactory.client.SimulationClient;
import com.ssafy.santafactory.dto.simulation.SimulationAcceptedResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class SimulationServiceTest {

    @Mock
    SimulationClient simulationClient;

    @InjectMocks
    SimulationService simulationService;

    @Test
    void requestSimulation_publishes_and_returns_queued() {
        SimulationRequest request = new SimulationRequest(
                "est_77_n3", 42L,
                new SimulationRequest.Warehouse(4, "01:00", "09:00", "13:00", "18:00", 480, 500),
                new SimulationRequest.Amr(3, 1.2, 1.0, 0.02, 100.0, 3600, 0.2, 8),
                List.of(), List.of());

        SimulationAcceptedResponse accepted = simulationService.requestSimulation(request);

        verify(simulationClient).publish(request);
        assertThat(accepted.runId()).isEqualTo("est_77_n3");
        assertThat(accepted.status()).isEqualTo("queued");
    }

    @Test
    void applyResult_handles_done_and_failed() {
        SimulationResponse done = new SimulationResponse("est_77_n3", "done", null,
                new SimulationResponse.Kpi(50, 50, 48, 48, 1740L, 210.5, 402.0, 87.3,
                        96.4, 182.0, 0.63, 0.004, 12480L, 0L));
        SimulationResponse failed = new SimulationResponse("est_77_n4", "failed", "stall", null);

        assertThatCode(() -> {
            simulationService.applyResult(done);
            simulationService.applyResult(failed);
        }).doesNotThrowAnyException();
    }
}
