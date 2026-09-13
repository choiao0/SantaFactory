package com.ssafy.santafactory.global.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.santafactory.global.auth.AuthProperties;
import com.ssafy.santafactory.global.auth.JwtAuthenticationFilter;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.global.exception.ErrorCode;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * 인증·인가 설정 (S15P21A106-186).
 *
 * <p><b>CSRF 를 끈 근거</b> — 토큰을 쿠키로 나르므로 CSRF 가 성립하는 구조인데, 쿠키에
 * {@code SameSite=Lax} 를 걸어 브라우저 단에서 막는다. 다른 사이트에서 온 POST·XHR 에는 쿠키가
 * 붙지 않는다. CSRF 토큰이 추가로 막아주는 건 (1) 서브도메인 공격 (2) GET 으로 상태를 바꾸는
 * 엔드포인트 (3) 구형 브라우저인데, 이 서비스는 단일 호스트에 GET 은 조회만 하고 최신 브라우저만
 * 대상이라 셋 다 해당하지 않는다. 켜면 프론트가 매 요청에 {@code X-XSRF-TOKEN} 을 붙여야 한다.
 *
 * <p><b>세션을 끈 근거</b> — access 토큰이 요청마다 주체를 실어오므로 서버 세션이 필요 없다.
 * STATELESS 로 두면 Spring 이 JSESSIONID 를 만들지 않는다.
 */
@Configuration
@EnableWebSecurity
@EnableConfigurationProperties(AuthProperties.class)
@RequiredArgsConstructor
public class SecurityConfig {

    /**
     * 인증 없이 열어두는 경로. 가입·로그인·갱신·로그아웃과 API 문서, 그리고 프론트 정적 자원.
     *
     * <p>로그아웃을 공개로 두는 이유: access 는 30분이라 만료된 상태로 로그아웃을 누르는 일이
     * 흔하다. 인증을 요구하면 그때 401 이 나고 <b>refresh 가 7일간 살아남는다</b> — 로그아웃의
     * 목적과 정반대다. 폐기 대상은 refresh 쿠키가 지목하고, 자기가 가진 토큰을 버리는 동작이라
     * 보호할 것이 없다.
     */
    private static final String[] PUBLIC = {
            "/api/auth/signup", "/api/auth/login", "/api/auth/refresh", "/api/auth/logout",
            "/swagger-ui/**", "/v3/api-docs/**",
            "/", "/index.html", "/assets/**", "/favicon.ico",
    };

    private final JwtAuthenticationFilter jwtFilter;
    private final ObjectMapper objectMapper;

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        return http
                .csrf(csrf -> csrf.disable())
                .httpBasic(basic -> basic.disable())
                .formLogin(form -> form.disable())
                .logout(logout -> logout.disable())   // 로그아웃은 AuthController 가 쿠키·Redis 까지 정리한다
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(PUBLIC).permitAll()
                        .requestMatchers("/api/admin/**").hasRole("ADMIN")
                        .anyRequest().authenticated())
                // 우리 필터가 SecurityContext 를 먼저 채워야 인가 단계가 판단할 수 있다
                .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class)
                .exceptionHandling(handling -> handling
                        .authenticationEntryPoint((request, response, e) ->
                                write(response, ErrorCode.UNAUTHORIZED))
                        .accessDeniedHandler((request, response, e) ->
                                write(response, ErrorCode.ACCESS_DENIED)))
                .build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    /** 인증·인가 실패도 { isSuccess, code, message } 로 내려 프론트가 한 가지 형식만 다루게 한다. */
    private void write(HttpServletResponse response, ErrorCode errorCode) throws java.io.IOException {
        response.setStatus(errorCode.getHttpStatus().value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        objectMapper.writeValue(response.getWriter(), ApiResponse.onFailure(errorCode, null));
    }
}
