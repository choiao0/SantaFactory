package com.ssafy.santafactory.client;

import com.ssafy.santafactory.dto.simulation.SimulationAcceptedResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

@Slf4j
@Component
@RequiredArgsConstructor
public class SimulationClient {

    private final RestClient aiRestClient;

    public SimulationAcceptedResponse requestSimulation(SimulationRequest request) {
        try {
            return aiRestClient.post()
                    .uri("/simulations")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(request)
                    .retrieve()
                    .body(SimulationAcceptedResponse.class);
        } catch (ResourceAccessException e) {
            log.error("AI 서버 연결 실패: runId={}", request.runId(), e);
            throw new GlobalException(ErrorCode.AI_SERVER_UNAVAILABLE);
        } catch (RestClientResponseException e) {
            log.error("AI 서버 응답 오류: runId={}, status={}, body={}",
                    request.runId(), e.getStatusCode(), e.getResponseBodyAsString());
            throw new GlobalException(ErrorCode.AI_SERVER_ERROR);
        }
    }
}
