package com.ssafy.santafactory.dto.auth;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/** 코드 확인 결과. 이 토큰을 가입 요청의 {@code email_token} 으로 보낸다. */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record EmailVerifyResponse(String emailToken) {
}
