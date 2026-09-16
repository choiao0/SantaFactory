package com.ssafy.santafactory.dto.auth;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** 인증 코드 발송 요청. */
public record EmailCodeRequest(
        @NotBlank @Email @Size(max = 255) String email
) {
}
