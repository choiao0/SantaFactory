package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.simulation.SimulationAcceptedResponse;
import com.ssafy.santafactory.dto.simulation.SimulationRequest;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.SimulationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Simulation", description = "시뮬레이션 요청 (프론트 → 백엔드 → 시뮬 엔진)")
@RestController
@RequestMapping("/api/simulations")
@RequiredArgsConstructor
public class SimulationController {

    private final SimulationService simulationService;

    @Operation(
            summary = "시뮬레이션 실행 요청",
            description = "요청 본문을 시뮬 엔진으로 전달하고 접수 응답(run_id, status)을 반환한다. 결과는 시뮬 엔진 콜백으로 수신한다.")
    @ApiResponses({
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "202", description = "시뮬 엔진 접수 완료"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "400", description = "요청 값 검증 실패 (COMMON400)"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "502", description = "시뮬 엔진 응답 오류 (SIM502)"),
            @io.swagger.v3.oas.annotations.responses.ApiResponse(responseCode = "503", description = "시뮬 엔진 연결 실패 (SIM503)")
    })
    @PostMapping
    public ResponseEntity<ApiResponse<SimulationAcceptedResponse>> request(
            @RequestBody @Valid SimulationRequest request) {
        SimulationAcceptedResponse accepted = simulationService.requestSimulation(request);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(ApiResponse.onSuccess(accepted));
    }
}
