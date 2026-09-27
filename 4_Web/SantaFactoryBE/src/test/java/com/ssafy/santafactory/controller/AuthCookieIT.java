package com.ssafy.santafactory.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.ssafy.santafactory.repository.MemberRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import com.ssafy.santafactory.support.PostgresSupport;
import com.ssafy.santafactory.support.RedisSupport;
import jakarta.servlet.http.Cookie;
import java.util.Arrays;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

/**
 * 쿠키를 통한 인증을 HTTP 단에서 관통한다.
 *
 * <p>서비스 단위 테스트로는 안 잡히는 것이 있어서 필요하다 — <b>쿠키의 {@code Path}</b> 다.
 * 예전에 refresh 쿠키 Path 를 {@code /api/auth/refresh} 로 좁혔더니, 브라우저가 로그아웃 요청에는
 * 쿠키를 보내지 않아 서버가 폐기할 토큰을 못 받고 <b>로그아웃이 조용히 실패</b>했다. 서비스에
 * 토큰을 직접 넘기는 테스트는 이걸 통과시킨다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(RedisSupport.class)
class AuthCookieIT extends PostgresSupport {

    @Autowired
    MockMvc mvc;

    @Autowired
    MemberRepository memberRepository;

    @Autowired
    WarehouseRepository warehouseRepository;

    @Autowired
    RedisSupport redis;

    private static final String EMAIL = "cookie@pumgo.test";
    private static final String PASSWORD = "cookie-pass-1234";

    @BeforeEach
    void signUp() throws Exception {
        warehouseRepository.deleteAllInBatch();
        memberRepository.deleteAllInBatch();
        mvc.perform(post("/api/auth/signup").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"%s","name":"김담당",
                                 "company":"품고물류","phone":"01012345678","email_token":"%s"}
                                """.formatted(EMAIL, PASSWORD, redis.verifiedToken(EMAIL))))
                .andExpect(status().isCreated());
    }

    private Cookie[] login() throws Exception {
        MvcResult result = mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"%s","password":"%s"}
                                """.formatted(EMAIL, PASSWORD)))
                .andExpect(status().isOk())
                .andReturn();
        return result.getResponse().getCookies();
    }

    private static Cookie cookie(Cookie[] cookies, String name) {
        return Arrays.stream(cookies).filter(c -> name.equals(c.getName())).findFirst().orElseThrow();
    }

    @Test
    void login_sets_httponly_cookies_and_never_returns_the_tokens() throws Exception {
        Cookie[] cookies = login();

        Cookie access = cookie(cookies, "access");
        Cookie refresh = cookie(cookies, "refresh");
        assertThat(access.isHttpOnly()).isTrue();
        assertThat(refresh.isHttpOnly()).isTrue();
        assertThat(access.getPath()).isEqualTo("/api");
        // 로그아웃도 이 쿠키를 봐야 하므로 갱신 경로보다 넓어야 한다
        assertThat(refresh.getPath()).isEqualTo("/api/auth");
    }

    @Test
    void the_access_cookie_authenticates_requests() throws Exception {
        Cookie access = cookie(login(), "access");

        mvc.perform(get("/api/auth/me").cookie(access)).andExpect(status().isOk());
        mvc.perform(get("/api/auth/me")).andExpect(status().isUnauthorized());
    }

    /** 이게 실측으로 잡은 버그의 회귀 테스트다 — 쿠키 Path 가 좁으면 여기서 깨진다. */
    @Test
    void logout_actually_invalidates_the_refresh_token() throws Exception {
        Cookie refresh = cookie(login(), "refresh");

        mvc.perform(post("/api/auth/logout").cookie(refresh)).andExpect(status().isOk());

        mvc.perform(post("/api/auth/refresh").cookie(refresh)).andExpect(status().isUnauthorized());
    }

    /**
     * 순서에 주의. 옛 쿠키를 먼저 재사용하면 <b>패밀리 폐기가 걸려 새 쿠키까지 죽는다</b> —
     * 그게 의도한 동작이라(재사용 = 복제본 신호), 새 쿠키가 산다는 것을 먼저 확인해야 한다.
     */
    @Test
    void refresh_rotates_and_the_old_cookie_stops_working() throws Exception {
        Cookie first = cookie(login(), "refresh");

        MvcResult rotated = mvc.perform(post("/api/auth/refresh").cookie(first))
                .andExpect(status().isOk())
                .andReturn();
        Cookie second = cookie(rotated.getResponse().getCookies(), "refresh");
        assertThat(second.getValue()).isNotEqualTo(first.getValue());

        // 새 쿠키는 살아 있다
        mvc.perform(post("/api/auth/refresh").cookie(second)).andExpect(status().isOk());
        // 옛 쿠키는 죽었다
        mvc.perform(post("/api/auth/refresh").cookie(first)).andExpect(status().isUnauthorized());
    }
}
