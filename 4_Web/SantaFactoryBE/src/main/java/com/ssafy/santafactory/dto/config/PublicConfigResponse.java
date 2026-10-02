package com.ssafy.santafactory.dto.config;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * 로그인 전에도 화면이 알아야 하는 서버 설정 (S15P21A106-283).
 *
 * @param trialMode 체험 모드 — 새 견적·3D 주행 검증을 받지 않고 데모 견적만 보여 준다. 화면은 안내 배너를 띄우고 요청 버튼을 숨긴다
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PublicConfigResponse(boolean trialMode) {
}
