package com.ssafy.santafactory.dto.auth;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * 회원가입. <b>역할을 받지 않는다</b> — 서버가 항상 USER 로 만든다. 받으면 요청 본문에
 * {@code "role":"ADMIN"} 을 끼워 넣어 관리자가 될 수 있다.
 *
 * <p>{@code company}·{@code phone} 이 필수인 이유: B2B 견적 서비스라 견적 뒤 영업 연결이 목적이고,
 * 연락 수단 없이 가입시키면 리드 데이터가 반쪽이 된다.
 *
 * <p>{@code emailToken} 은 코드 확인({@code POST /api/auth/email/verify})이 준 값이다. 없거나 그 이메일로
 * 발급된 것이 아니면 가입이 거부된다 — 연락 가능한 이메일만 회원이 되게 (S15P21A106-198).
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record SignUpRequest(
        @NotBlank @Email @Size(max = 255) String email,
        @NotBlank @Size(min = 8, max = 64) String password,
        @NotBlank @Size(max = 50) String name,
        @NotBlank @Size(max = 100) String company,
        @NotBlank @Pattern(regexp = "[0-9-]{9,20}", message = "숫자와 하이픈만 입력해 주세요.") String phone,
        @NotBlank String emailToken
) {

    /** 하이픈을 떼고 저장한다 — 010-1234-5678 과 01012345678 이 다른 값이 되지 않게. */
    public String normalizedPhone() {
        return phone.replaceAll("[^0-9]", "");
    }
}
