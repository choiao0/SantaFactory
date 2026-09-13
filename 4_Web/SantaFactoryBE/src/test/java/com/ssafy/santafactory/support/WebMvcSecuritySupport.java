package com.ssafy.santafactory.support;

import com.ssafy.santafactory.global.auth.AuthProperties;
import com.ssafy.santafactory.global.auth.JwtProvider;
import com.ssafy.santafactory.global.auth.RefreshTokenBlacklist;
import com.ssafy.santafactory.global.config.SecurityConfig;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.ContextConfiguration;

/**
 * {@code @WebMvcTest} 가 Security 와 함께 뜨게 해주는 보조 설정.
 *
 * <p>필요한 이유: {@code @WebMvcTest} 는 웹 계층 빈만 올리는데 <b>{@code Filter} 빈은 포함시킨다.</b>
 * {@code JwtAuthenticationFilter} 가 {@code OncePerRequestFilter} 라서 딸려 올라오고, 그게 참조하는
 * {@code JwtProvider} 는 일반 {@code @Component} 라 슬라이스에서 빠져 의존성이 빈다.
 * 여기서 그 빈들만 최소로 채운다.
 *
 * <p>{@code SecurityConfig} 자체도 함께 가져온다. 안 가져오면 Spring Boot 의 <b>기본</b> 보안
 * 설정이 적용되는데, 기본값은 CSRF 가 켜져 있어 POST 가 403 이 된다 — 운영 설정은 CSRF 를 끄고
 * {@code SameSite=Lax} 로 막으므로, 기본값으로 테스트하면 운영과 다른 동작을 검증하게 된다.
 *
 * <p>슬라이스 테스트는 인증 자체를 검증하지 않으므로(그건 통합 테스트 몫) 토큰 발급에 쓰는
 * 서명 키는 아무 값이면 된다. 컨트롤러 테스트는 {@code @WithMockUser} 로 주체를 넣는다.
 */
@TestConfiguration
@ContextConfiguration
@Import(SecurityConfig.class)
public class WebMvcSecuritySupport {

    // AuthProperties 는 SecurityConfig 의 @EnableConfigurationProperties 가 만든다.
    // 값은 test/resources/application.yml 의 auth.secret 에서 온다 — 여기서 또 정의하면 빈이 둘이 된다.

    @Bean
    public JwtProvider jwtProvider(AuthProperties props) {
        return new JwtProvider(props);
    }

    /** Redis 에 붙지 않는다 — 슬라이스 테스트는 폐기 목록을 쓰지 않는다. */
    @Bean
    public RefreshTokenBlacklist refreshTokenStore(AuthProperties props) {
        return new RefreshTokenBlacklist(org.mockito.Mockito.mock(StringRedisTemplate.class), props);
    }

    // PasswordEncoder 는 SecurityConfig 가 제공하므로 여기서 정의하지 않는다 (중복이면 컨텍스트 실패)
}
