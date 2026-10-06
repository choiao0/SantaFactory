package com.ssafy.santafactory.global.auth;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 체험 모드 스위치 (S15P21A106-283).
 *
 * @param enabled 켜면 새 견적·3D 주행 검증·창고 등록을 받지 않고, 데모 회원의 견적을 가입한 누구나 읽기만 한다
 */
@ConfigurationProperties(prefix = "trial")
public record TrialProperties(@DefaultValue("false") boolean enabled) {
}
