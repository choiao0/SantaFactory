package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.robot.RobotModelResponse;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.RobotService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "AMR", description = "견적에 쓸 수 있는 AMR 모델")
@RestController
@RequestMapping("/api/robots")
@RequiredArgsConstructor
public class RobotController {

    private final RobotService robotService;

    @Operation(summary = "AMR 모델 목록", description = "모델별 사양·단가 1건씩. 01 화면 모델 카드")
    @GetMapping
    public ApiResponse<List<RobotModelResponse>> models() {
        return ApiResponse.onSuccess(robotService.models());
    }
}
