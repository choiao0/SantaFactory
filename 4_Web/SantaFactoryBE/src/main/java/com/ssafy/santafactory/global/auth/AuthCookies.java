package com.ssafy.santafactory.global.auth;

import jakarta.servlet.http.HttpServletRequest;
import java.time.Duration;
import java.util.Arrays;
import java.util.Optional;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

/**
 * 인증 쿠키 생성·삭제.
 *
 * <p>토큰을 헤더가 아니라 쿠키로 나른다. 이유는 견적 진행 스트림이다 — {@code EventSource} 는
 * 커스텀 헤더를 붙일 수 없어서 {@code Authorization} 방식으로는 SSE 구독이 인증을 통과하지 못한다.
 * 쿠키는 브라우저가 자동으로 첨부하므로 {@code EventSource} 도 그냥 된다.
 *
 * <p>속성 셋의 뜻:
 * <ul>
 *   <li>{@code HttpOnly} — JS 가 읽지 못한다. XSS 로도 토큰 값을 빼갈 수 없다</li>
 *   <li>{@code SameSite=Lax} — 다른 사이트에서 온 POST·XHR 에는 쿠키가 붙지 않는다 (CSRF 대비).
 *       링크 클릭으로 들어오는 GET 만 예외라, 조회만 하는 우리 GET API 에는 위험이 없다</li>
 *   <li>{@code Secure} — HTTPS 전용. HTTP 환경에서는 설정으로 끈다. 안 끄면 쿠키가 전달되지 않는다</li>
 *   <li>{@code Path} — refresh 는 갱신 요청에만 붙어서, 나머지 모든 API 호출에는 실리지 않는다</li>
 * </ul>
 */
@Component
public class AuthCookies {

    public static final String ACCESS = "access";
    public static final String REFRESH = "refresh";

    /** access 는 모든 API 요청에 붙어야 한다. */
    private static final String ACCESS_PATH = "/api";

    /**
     * refresh 는 인증 엔드포인트에만 붙는다 — 견적·창고 같은 일반 API 호출에는 실리지 않아
     * 노출 면이 줄어든다.
     *
     * <p>{@code /api/auth/refresh} 로 더 좁히면 <b>로그아웃이 토큰을 못 본다</b>. 브라우저는
     * Path 가 맞는 요청에만 쿠키를 보내므로, 그러면 서버가 폐기할 토큰을 받지 못해 로그아웃이
     * 쿠키만 지우고 Redis 의 refresh 는 살아남는다 (2026-09-11 실측).
     */
    private static final String REFRESH_PATH = "/api/auth";

    private final AuthProperties props;

    public AuthCookies(AuthProperties props) {
        this.props = props;
    }

    public HttpHeaders issue(String accessToken, String refreshToken) {
        HttpHeaders headers = new HttpHeaders();
        headers.add(HttpHeaders.SET_COOKIE,
                build(ACCESS, accessToken, ACCESS_PATH, props.accessTtl()).toString());
        headers.add(HttpHeaders.SET_COOKIE,
                build(REFRESH, refreshToken, REFRESH_PATH, props.refreshTtl()).toString());
        return headers;
    }

    /** 만료 0으로 덮어써 삭제한다. 경로가 발급 때와 같아야 브라우저가 같은 쿠키로 인식한다. */
    public HttpHeaders clear() {
        HttpHeaders headers = new HttpHeaders();
        headers.add(HttpHeaders.SET_COOKIE, build(ACCESS, "", ACCESS_PATH, Duration.ZERO).toString());
        headers.add(HttpHeaders.SET_COOKIE, build(REFRESH, "", REFRESH_PATH, Duration.ZERO).toString());
        return headers;
    }

    public static Optional<String> read(HttpServletRequest request, String name) {
        if (request.getCookies() == null) {
            return Optional.empty();
        }
        return Arrays.stream(request.getCookies())
                .filter(cookie -> name.equals(cookie.getName()))
                .map(jakarta.servlet.http.Cookie::getValue)
                .filter(value -> value != null && !value.isBlank())
                .findFirst();
    }

    private ResponseCookie build(String name, String value, String path, Duration maxAge) {
        return ResponseCookie.from(name, value)
                .httpOnly(true)
                .secure(props.secureCookie())
                .sameSite("Lax")
                .path(path)
                .maxAge(maxAge)
                .build();
    }
}
