package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.simulation.SimulationResponse;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.global.config.AiProperties;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.service.SimulationService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@RestController
@RequestMapping("/api/ai/simulations")
@RequiredArgsConstructor
public class AiCallbackController {

    private static final String TOKEN_HEADER = "X-AI-Callback-Token";

    private final SimulationService simulationService;
    private final AiProperties aiProperties;

    @PostMapping
    public ApiResponse<Void> callback(
            @RequestHeader(value = TOKEN_HEADER, required = false) String token,
            @RequestBody @Valid SimulationResponse response) {
        verifyToken(token);
        simulationService.applyResult(response);
        return ApiResponse.onSuccess();
    }

    private void verifyToken(String token) {
        String expected = aiProperties.callbackToken();
        if (token == null || expected == null || !MessageDigest.isEqual(
                token.getBytes(StandardCharsets.UTF_8), expected.getBytes(StandardCharsets.UTF_8))) {
            throw new GlobalException(ErrorCode.AI_CALLBACK_UNAUTHORIZED);
        }
    }
}
