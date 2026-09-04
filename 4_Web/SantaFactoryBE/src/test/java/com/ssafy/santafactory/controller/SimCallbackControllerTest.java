package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.global.config.SimClientConfig;
import com.ssafy.santafactory.service.SimulationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(SimCallbackController.class)
@Import(SimClientConfig.class)
@TestPropertySource(properties = {
        "sim.base-url=http://localhost:8000",
        "sim.connect-timeout=1s",
        "sim.read-timeout=1s",
        "sim.callback-token=test-token"
})
class SimCallbackControllerTest {

    private static final String BODY = """
            { "run_id": "est_77_n3", "status": "done", "error": null,
              "kpi": { "orders_total": 50, "orders_completed": 50, "throughput_orders_per_h": 96.4 } }
            """;

    @Autowired
    MockMvc mockMvc;

    @MockBean
    SimulationService simulationService;

    @Test
    void callback_with_valid_token_returns_200() throws Exception {
        mockMvc.perform(post("/api/sim/results")
                        .header("X-Sim-Callback-Token", "test-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.isSuccess").value(true))
                .andExpect(jsonPath("$.code").value("COMMON200"));

        verify(simulationService).applyResult(any(SimulationResponse.class));
    }

    @Test
    void callback_with_wrong_token_returns_401() throws Exception {
        mockMvc.perform(post("/api/sim/results")
                        .header("X-Sim-Callback-Token", "wrong")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(BODY))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("SIM401"));

        verify(simulationService, never()).applyResult(any());
    }

    @Test
    void callback_without_token_returns_401() throws Exception {
        mockMvc.perform(post("/api/sim/results")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(BODY))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void callback_without_run_id_returns_400() throws Exception {
        mockMvc.perform(post("/api/sim/results")
                        .header("X-Sim-Callback-Token", "test-token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"status\": \"done\" }"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("COMMON400"));
    }
}
