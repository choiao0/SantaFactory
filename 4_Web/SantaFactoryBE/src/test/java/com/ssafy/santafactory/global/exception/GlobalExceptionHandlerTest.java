package com.ssafy.santafactory.global.exception;

import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.ssafy.santafactory.controller.AuthController;
import com.ssafy.santafactory.global.auth.AuthCookies;
import com.ssafy.santafactory.service.auth.AuthService;
import com.ssafy.santafactory.support.WebMvcSecuritySupport;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/**
 * 본문을 읽지 못하는 요청은 클라이언트 잘못(400)이다. 처리기가 없으면 500 으로 떨어져 서버 장애로 보이고
 * 에러 로그에 스택이 쌓인다 — 이메일 인증 발송 테스트 중 깨진 UTF-8 본문으로 실측(S15P21A106-198).
 * 인증이 필요 없는 가입 경로로 확인한다.
 */
@WebMvcTest(AuthController.class)
@Import(WebMvcSecuritySupport.class)
class GlobalExceptionHandlerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    AuthService authService;

    @MockBean
    AuthCookies authCookies;

    @Test
    void malformed_json_is_a_400_not_a_500() throws Exception {
        mvc.perform(post("/api/auth/signup").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"a@b.test\", \"password\": "))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.isSuccess").value(false))
                .andExpect(jsonPath("$.code").value("COMMON400"));
        verify(authService, never()).signUp(ArgumentMatchers.any());
    }

    @Test
    void an_invalid_utf8_body_is_a_400() throws Exception {
        byte[] body = "{\"email\":\"a@b.test\",\"name\":\"".getBytes(StandardCharsets.UTF_8);
        byte[] broken = new byte[body.length + 3];
        System.arraycopy(body, 0, broken, 0, body.length);
        broken[body.length] = (byte) 0xBD;   // UTF-8 시작 바이트로 올 수 없는 값 (cp949 로 보낸 한글의 흔적)
        broken[body.length + 1] = '"';
        broken[body.length + 2] = '}';

        mvc.perform(post("/api/auth/signup").contentType(MediaType.APPLICATION_JSON).content(broken))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("COMMON400"));
    }

    @Test
    void a_missing_body_is_a_400() throws Exception {
        mvc.perform(post("/api/auth/signup").contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("COMMON400"));
    }
}
