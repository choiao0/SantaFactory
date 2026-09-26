package com.ssafy.santafactory.dto.auth;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/** 인증 코드 확인 요청. 코드는 숫자 6자리다. */
public record EmailVerifyRequest(
        @NotBlank @Email @Size(max = 255) String email,
        @NotBlank @Pattern(regexp = "[0-9]{6}", message = "인증 코드는 숫자 6자리입니다.") String code
) {
}
