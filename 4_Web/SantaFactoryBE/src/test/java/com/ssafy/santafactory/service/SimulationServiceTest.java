package com.ssafy.santafactory.service;

import com.ssafy.santafactory.client.SimulationClient;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class SimulationServiceTest {

    @Mock
    SimulationClient simulationClient;

    @InjectMocks
    SimulationService simulationService;

    private final SimulationRequest base = new SimulationRequest(
            "est_77", 42L, 21600L, "in,in,out,out,out,out", 48.0, 22.5,
            new SimulationRequest.Warehouse(4, "01:00", "09:00", "13:00", "18:00", 480, 500),
            new SimulationRequest.Amr(0, 1.2, 1.0, 0.02, 100.0, 3600, 0.2, 8),
            List.of(new SimulationRequest.Inbound(5001L, 3L,
                    List.of(new SimulationRequest.Line(7L, "A2", 20)))),
            List.of(new SimulationRequest.Outbound(1001L, 0L,
                    List.of(new SimulationRequest.Line(7L, "A2", 1)))));

    @Test
    void publishRuns_publishes_one_message_per_amr_count() {
        List<String> runIds = simulationService.publishRuns(base, List.of(3, 5, 8));

        ArgumentCaptor<SimulationRequest> captor = ArgumentCaptor.forClass(SimulationRequest.class);
        verify(simulationClient, times(3)).publish(captor.capture());
        List<SimulationRequest> published = captor.getAllValues();

        assertThat(runIds).containsExactly("est_77_n3", "est_77_n5", "est_77_n8");
        assertThat(published).extracting(SimulationRequest::runId).containsExactly("est_77_n3", "est_77_n5", "est_77_n8");
        assertThat(published).extracting(m -> m.amr().count()).containsExactly(3, 5, 8);

        SimulationRequest first = published.get(0);
        assertThat(first.seed()).isEqualTo(base.seed());
        assertThat(first.warehouse()).isEqualTo(base.warehouse());
        assertThat(first.inbound()).isEqualTo(base.inbound());
        assertThat(first.outbound()).isEqualTo(base.outbound());
        assertThat(first.amr().speedEmpty()).isEqualTo(1.2);
        assertThat(first.amr().capacity()).isEqualTo(8);
    }

    @Test
    void applyResult_handles_done_and_failed() {
        SimulationResponse done = new SimulationResponse("est_77_n3", "done", null,
                new SimulationResponse.Kpi(50, 50, 48, 48, 1740L, 210.5, 402.0, 87.3,
                        96.4, 182.0, 0.63, 0.004, 12480L, 0L));
        SimulationResponse failed = new SimulationResponse("est_77_n5", "failed", "stall", null);

        assertThatCode(() -> {
            simulationService.applyResult(done);
            simulationService.applyResult(failed);
        }).doesNotThrowAnyException();
    }
}
