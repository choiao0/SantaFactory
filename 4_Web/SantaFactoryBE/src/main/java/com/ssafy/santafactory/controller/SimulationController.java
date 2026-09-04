package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.simulation.SimulationAcceptedResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.SimulationService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/simulations")
@RequiredArgsConstructor
public class SimulationController {

    private final SimulationService simulationService;

    @PostMapping
    public ResponseEntity<ApiResponse<SimulationAcceptedResponse>> request(
            @RequestBody @Valid SimulationRequest request) {
        SimulationAcceptedResponse accepted = simulationService.requestSimulation(request);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(ApiResponse.onSuccess(accepted));
    }
}
