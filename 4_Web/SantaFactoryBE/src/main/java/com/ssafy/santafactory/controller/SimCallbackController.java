package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.global.config.SimProperties;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.service.SimulationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.enums.ParameterIn;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Tag(name = "Sim Callback", description = "시뮬 엔진이 호출하는 결과 수신 엔드포인트 (시뮬 엔진 → 백엔드)")
@RestController
@RequestMapping("/api/sim/results")
@RequiredArgsConstructor
public class SimCallbackController {

    private static final String TOKEN_HEADER = "X-Sim-Callback-Token";

    private final SimulationService simulationService;
    private final SimProperties simProperties;

    @Operation(
            summary = "시뮬레이션 결과 콜백",
            description = "시뮬 엔진이 시뮬레이션 완료 후 KPI 결과를 전달한다. status 가 failed 면 error 에 사유, kpi 는 null.")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "200", description = "정상 반영"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "run_id 또는 status 누락 (COMMON400)"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "401", description = "콜백 토큰 불일치 (SIM401)")
    })
    @PostMapping
    public ApiResponse<Void> callback(
            @Parameter(in = ParameterIn.HEADER, name = TOKEN_HEADER, required = true, description = "SIM_CALLBACK_TOKEN 과 동일한 값")
            @RequestHeader(value = TOKEN_HEADER, required = false) String token,
            @RequestBody @Valid SimulationResponse response) {
        verifyToken(token);
        simulationService.applyResult(response);
        return ApiResponse.onSuccess();
    }

    private void verifyToken(String token) {
        String expected = simProperties.callbackToken();
        if (token == null || expected == null || !MessageDigest.isEqual(
                token.getBytes(StandardCharsets.UTF_8), expected.getBytes(StandardCharsets.UTF_8))) {
            throw new GlobalException(ErrorCode.SIM_CALLBACK_UNAUTHORIZED);
        }
    }
}
