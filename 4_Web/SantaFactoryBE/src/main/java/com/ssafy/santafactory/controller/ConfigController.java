package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.config.PublicConfigResponse;
import com.ssafy.santafactory.global.auth.TrialMode;
import com.ssafy.santafactory.global.common.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "설정", description = "로그인 전에도 화면이 읽는 서버 설정")
@RestController
@RequestMapping("/api/config")
@RequiredArgsConstructor
public class ConfigController {

    private final TrialMode trialMode;

    @Operation(summary = "공개 설정",
            description = "체험 모드 여부. 켜져 있으면 새 견적·3D 주행 검증은 403(TRIAL403_1)이고 데모 견적만 볼 수 있다. "
                    + "로그인·가입 화면에도 안내 배너를 띄우려고 토큰 없이 연다 (S15P21A106-283)")
    @GetMapping
    public ApiResponse<PublicConfigResponse> config() {
        return ApiResponse.onSuccess(new PublicConfigResponse(trialMode.enabled()));
    }
}
