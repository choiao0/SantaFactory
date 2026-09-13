package com.ssafy.santafactory.service.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.ssafy.santafactory.dto.auth.LoginRequest;
import com.ssafy.santafactory.dto.auth.SignUpRequest;
import com.ssafy.santafactory.entity.member.Role;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.MemberRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import com.ssafy.santafactory.support.PostgresSupport;
import com.ssafy.santafactory.support.RedisSupport;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

/**
 * 가입 → 로그인 → 갱신(회전) → 로그아웃을 실제 Postgres·Redis 로 관통한다.
 *
 * <p>refresh 회전과 재사용 감지는 저장소 동작에 달려 있어 목으로는 검증이 안 된다.
 */
@SpringBootTest
@Import(RedisSupport.class)   // @TestComponent 는 자동 등록되지 않는다
class AuthServiceTest extends PostgresSupport {

    @Autowired
    AuthService authService;

    @Autowired
    MemberRepository memberRepository;

    @Autowired
    WarehouseRepository warehouseRepository;

    @Autowired
    RedisSupport redis;

    private static final String EMAIL = "lead@pumgo.test";
    private static final String PASSWORD = "pumgo-pass-1234";

    /**
     * 같은 DB 를 다른 테스트 클래스와 공유하므로, 앞선 테스트가 남긴 창고를 먼저 지운다.
     * warehouses.member_id 가 members 를 참조해서 순서를 뒤집으면 FK 위반이 난다.
     */
    @BeforeEach
    void clean() {
        warehouseRepository.deleteAllInBatch();
        memberRepository.deleteAllInBatch();
        redis.flush();
    }

    private void givenSignedUp() {
        authService.signUp(new SignUpRequest(EMAIL, PASSWORD, "김담당", "품고물류", "010-1234-5678"));
    }

    @Test
    void sign_up_stores_a_hash_and_always_makes_a_user() {
        var response = authService.signUp(
                new SignUpRequest(EMAIL, PASSWORD, "김담당", "품고물류", "010-1234-5678"));

        assertThat(response.role()).isEqualTo(Role.USER);
        // 하이픈을 뗀 숫자만 저장한다 — 같은 번호가 다른 값으로 남지 않게
        assertThat(response.phone()).isEqualTo("01012345678");

        var saved = memberRepository.findByEmail(EMAIL).orElseThrow();
        assertThat(saved.getPassword()).isNotEqualTo(PASSWORD).startsWith("$2");
    }

    @Test
    void duplicate_email_is_rejected() {
        givenSignedUp();

        assertThatThrownBy(() -> authService.signUp(
                new SignUpRequest(EMAIL, "another-pass", "박과장", "품고물류", "01099998888")))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.EMAIL_ALREADY_USED);
    }

    /** 없는 이메일과 틀린 비밀번호가 같은 오류여야 한다 — 구분되면 가입 여부가 새어나간다. */
    @Test
    void a_wrong_password_and_an_unknown_email_look_the_same() {
        givenSignedUp();

        assertThatThrownBy(() -> authService.login(new LoginRequest(EMAIL, "wrong")))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.INVALID_CREDENTIALS);
        assertThatThrownBy(() -> authService.login(new LoginRequest("nobody@test", PASSWORD)))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.INVALID_CREDENTIALS);
    }

    @Test
    void login_issues_both_tokens() {
        givenSignedUp();

        var tokens = authService.login(new LoginRequest(EMAIL, PASSWORD));

        assertThat(tokens.accessToken()).isNotBlank();
        assertThat(tokens.refreshToken()).isNotBlank();
        assertThat(tokens.member().getEmail()).isEqualTo(EMAIL);
    }

    @Test
    void refresh_rotates_the_token() {
        givenSignedUp();
        var first = authService.login(new LoginRequest(EMAIL, PASSWORD));

        var second = authService.refresh(first.refreshToken());

        assertThat(second.refreshToken()).isNotEqualTo(first.refreshToken());
        assertThat(second.accessToken()).isNotBlank();
    }

    /**
     * 회전의 핵심. 이미 쓴 refresh 가 다시 오면 복제본이 돌고 있다는 뜻이므로 거부한다.
     * 이게 없으면 탈취된 토큰을 계속 쓸 수 있다.
     */
    @Test
    void a_reused_refresh_token_is_rejected() {
        givenSignedUp();
        var first = authService.login(new LoginRequest(EMAIL, PASSWORD));
        authService.refresh(first.refreshToken());   // 여기서 소비된다

        assertThatThrownBy(() -> authService.refresh(first.refreshToken()))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.REFRESH_TOKEN_INVALID);
    }

    /**
     * 재사용 감지의 나머지 절반 (RFC 9700). 거부만 하면 늦게 온 쪽만 막히고, 먼저 갱신한 쪽
     * (공격자일 수 있다)은 최신 토큰으로 계속 쓴다. 그래서 그 회원의 토큰을 전부 끊는다.
     */
    @Test
    void a_reused_token_kills_every_session_of_that_member() {
        givenSignedUp();
        var phone = authService.login(new LoginRequest(EMAIL, PASSWORD));
        var desktop = authService.login(new LoginRequest(EMAIL, PASSWORD));
        var rotated = authService.refresh(phone.refreshToken());   // 폰에서 한 번 갱신

        // 탈취된 옛 토큰이 다시 들어온다
        assertThatThrownBy(() -> authService.refresh(phone.refreshToken()))
                .isInstanceOf(GlobalException.class);

        // 갱신으로 받은 최신 토큰도, 다른 기기 토큰도 함께 끊겨야 한다
        assertThatThrownBy(() -> authService.refresh(rotated.refreshToken()))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.REFRESH_TOKEN_INVALID);
        assertThatThrownBy(() -> authService.refresh(desktop.refreshToken()))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.REFRESH_TOKEN_INVALID);
    }

    /** access 토큰을 갱신 요청에 들이밀 수 없어야 한다 — 같은 키로 서명되므로 종류 검사가 유일한 방어다. */
    @Test
    void an_access_token_cannot_be_used_as_a_refresh_token() {
        givenSignedUp();
        var tokens = authService.login(new LoginRequest(EMAIL, PASSWORD));

        assertThatThrownBy(() -> authService.refresh(tokens.accessToken()))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.REFRESH_TOKEN_INVALID);
    }

    @Test
    void logout_kills_only_that_device() {
        givenSignedUp();
        var phone = authService.login(new LoginRequest(EMAIL, PASSWORD));
        var desktop = authService.login(new LoginRequest(EMAIL, PASSWORD));

        authService.logout(phone.refreshToken());

        assertThatThrownBy(() -> authService.refresh(phone.refreshToken()))
                .isInstanceOf(GlobalException.class);
        // 다른 기기는 살아 있어야 한다
        assertThat(authService.refresh(desktop.refreshToken()).accessToken()).isNotBlank();
    }

    @Test
    void an_unknown_refresh_token_is_rejected() {
        assertThatThrownBy(() -> authService.refresh("made-up-token"))
                .isInstanceOf(GlobalException.class)
                .hasFieldOrPropertyWithValue("errorCode", ErrorCode.REFRESH_TOKEN_INVALID);
    }
}
