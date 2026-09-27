package com.ssafy.santafactory.global.auth;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 인증 설정 (S15P21A106-186).
 *
 * @param secret        JWT 서명 키. HS256 이라 32바이트(256비트) 이상이어야 한다
 * @param accessTtl     access 토큰 수명. 짧게 두고 refresh 로 갱신한다
 * @param refreshTtl    refresh 토큰 수명. Redis TTL 로도 쓰인다
 * @param secureCookie  쿠키에 Secure 를 붙일지. HTTP 로 뜨는 환경에서는 꺼야 쿠키가 전달된다
 */
@ConfigurationProperties(prefix = "auth")
public record AuthProperties(
        String secret,
        @DefaultValue("15m") Duration accessTtl,
        @DefaultValue("7d") Duration refreshTtl,
        @DefaultValue("false") boolean secureCookie
) {
}
