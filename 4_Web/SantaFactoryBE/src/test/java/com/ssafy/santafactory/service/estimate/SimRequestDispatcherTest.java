package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.service.SimulationService;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunsQueued;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SimRequestDispatcherTest {

    @Mock
    SimulationService simulationService;
    @Mock
    EstimateService estimateService;
    @Mock
    SimulationRequest request;

    @InjectMocks
    SimRequestDispatcher dispatcher;

    @Test
    void publishes_every_fleet_size_in_order() {
        dispatcher.onRunsQueued(new RunsQueued(7L, request, List.of(1, 2, 3)));

        verify(simulationService).publishRun(request, 1);
        verify(simulationService).publishRun(request, 2);
        verify(simulationService).publishRun(request, 3);
        verify(estimateService, never()).failUnpublished(any(), any(), any());
    }

    @Test
    void a_publish_failure_fails_that_run_and_the_rest_but_keeps_the_ones_already_sent() {
        when(simulationService.publishRun(request, 1)).thenReturn("est_7_n1");
        doThrow(new GlobalException(ErrorCode.SIM_QUEUE_UNAVAILABLE)).when(simulationService).publishRun(request, 2);

        dispatcher.onRunsQueued(new RunsQueued(7L, request, List.of(1, 2, 3, 4)));

        verify(simulationService, times(2)).publishRun(any(), anyInt());
        verify(estimateService).failUnpublished(eq(7L), eq(List.of(2, 3, 4)), eq(ErrorCode.SIM_QUEUE_UNAVAILABLE.getMessage()));
    }
}
