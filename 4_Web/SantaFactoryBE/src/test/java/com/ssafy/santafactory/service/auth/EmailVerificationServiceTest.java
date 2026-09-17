package com.ssafy.santafactory.service.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.support.PostgresSupport;
import com.ssafy.santafactory.support.RedisSupport;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;

/**
 * 코드 발급 → 확인 → 토큰 소비를 실제 Redis 로 관통한다. 메일은 보내지 않고 본문에서 코드를 읽는다 —
 * 사용자가 메일함에서 보는 것과 같은 경로다.
 */
@SpringBootTest
@Import(RedisSupport.class)
class EmailVerificationServiceTest extends PostgresSupport {

    private static final Pattern CODE = Pattern.compile("\\b(\\d{6})\\b");
    private static final String EMAIL = "lead@pumgo.test";

    @Autowired
    EmailVerificationService service;

    @Autowired
    RedisSupport redis;

    @MockBean
    EmailSender emailSender;

    @BeforeEach
    void clean() {
        redis.flush();
    }

    private String sentCode(int nth) {
        ArgumentCaptor<String> body = ArgumentCaptor.captor();
        verify(emailSender, times(nth)).send(eq(EMAIL), any(), body.capture());
        Matcher m = CODE.matcher(body.getAllValues().get(nth - 1));
        assertThat(m.find()).isTrue();
        return m.group(1);
    }

    @Test
    void the_mailed_code_verifies_and_yields_a_token_that_sign_up_consumes_once() {
        service.issue(EMAIL);
        String code = sentCode(1);

        String token = service.verify(EMAIL, code);

        assertThat(token).isNotBlank();
        // 이메일은 대소문자·공백을 무시하고 같은 것으로 본다
        service.consume(" Lead@Pumgo.test ", token);
        assertThatThrownBy(() -> service.consume(EMAIL, token))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_NOT_VERIFIED);
    }

    @Test
    void a_code_is_single_use() {
        service.issue(EMAIL);
        String code = sentCode(1);
        service.verify(EMAIL, code);

        assertThatThrownBy(() -> service.verify(EMAIL, code))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_CODE_EXPIRED);
    }

    @Test
    void a_wrong_code_is_rejected_and_the_fifth_miss_discards_the_code() {
        service.issue(EMAIL);
        String code = sentCode(1);
        String wrong = code.equals("000000") ? "000001" : "000000";

        for (int i = 0; i < 4; i++) {
            assertThatThrownBy(() -> service.verify(EMAIL, wrong))
                    .isInstanceOf(GlobalException.class)
                    .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_CODE_INVALID);
        }
        // 다섯 번째 실패에서 코드가 버려진다 — 그 뒤엔 맞는 코드도 소용없다
        assertThatThrownBy(() -> service.verify(EMAIL, wrong))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_CODE_EXPIRED);
        assertThatThrownBy(() -> service.verify(EMAIL, code))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_CODE_EXPIRED);
    }

    @Test
    void resending_inside_the_cooldown_is_refused_and_sends_nothing() {
        service.issue(EMAIL);

        assertThatThrownBy(() -> service.issue(EMAIL))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_SEND_TOO_OFTEN);
        verify(emailSender, times(1)).send(eq(EMAIL), any(), any());
    }

    @Test
    void verifying_without_a_code_reports_expired() {
        assertThatThrownBy(() -> service.verify(EMAIL, "123456"))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_CODE_EXPIRED);
    }

    @Test
    void a_token_only_works_for_the_email_it_was_issued_for() {
        service.issue(EMAIL);
        String token = service.verify(EMAIL, sentCode(1));

        assertThatThrownBy(() -> service.consume("other@pumgo.test", token))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_NOT_VERIFIED);
    }
}
