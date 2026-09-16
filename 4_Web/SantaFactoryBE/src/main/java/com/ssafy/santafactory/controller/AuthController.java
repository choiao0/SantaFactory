package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.auth.EmailCodeRequest;
import com.ssafy.santafactory.dto.auth.EmailVerifyRequest;
import com.ssafy.santafactory.dto.auth.EmailVerifyResponse;
import com.ssafy.santafactory.dto.auth.LoginRequest;
import com.ssafy.santafactory.dto.auth.MemberResponse;
import com.ssafy.santafactory.dto.auth.SignUpRequest;
import com.ssafy.santafactory.global.auth.AuthCookies;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.auth.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * 인증 (S15P21A106-186).
 *
 * <p>토큰은 응답 본문에 담지 않고 <b>HttpOnly 쿠키</b>로만 내린다. 프론트는 토큰을 볼 수도,
 * 저장할 수도 없다 — 저장 위치를 고민할 일이 없고 XSS 로 값이 새지도 않는다.
 */
@Tag(name = "인증", description = "회원가입·로그인·토큰 갱신")
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;
    private final AuthCookies authCookies;

    @Operation(summary = "가입 인증 코드 발송",
            description = "이메일로 6자리 코드를 보낸다. 같은 이메일은 60초에 한 번만(429). 이미 가입된 이메일은 409.")
    @PostMapping("/email/code")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ApiResponse<Void> sendEmailCode(@Valid @RequestBody EmailCodeRequest request) {
        authService.requestEmailCode(request.email());
        return ApiResponse.onSuccess();
    }

    @Operation(summary = "가입 인증 코드 확인",
            description = "맞으면 email_token 을 준다. 가입 요청에 실어 보내야 한다. 5회 틀리거나 5분이 지나면 코드부터 다시.")
    @PostMapping("/email/verify")
    public ApiResponse<EmailVerifyResponse> verifyEmailCode(@Valid @RequestBody EmailVerifyRequest request) {
        return ApiResponse.onSuccess(authService.verifyEmailCode(request.email(), request.code()));
    }

    @Operation(summary = "회원가입",
            description = "역할은 요청에서 받지 않고 항상 USER 로 만든다. 관리자는 가입으로 만들 수 없다. "
                    + "email_token 은 코드 확인이 준 값이어야 한다(아니면 403).")
    @PostMapping("/signup")
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<MemberResponse> signUp(@Valid @RequestBody SignUpRequest request) {
        return ApiResponse.onSuccess(authService.signUp(request));
    }

    @Operation(summary = "로그인", description = "access(30분)·refresh(7일) 쿠키를 내린다")
    @PostMapping("/login")
    public ResponseEntity<ApiResponse<MemberResponse>> login(@Valid @RequestBody LoginRequest request) {
        var tokens = authService.login(request);
        return ResponseEntity.ok()
                .headers(authCookies.issue(tokens.accessToken(), tokens.refreshToken()))
                .body(ApiResponse.onSuccess(MemberResponse.from(tokens.member())));
    }

    @Operation(summary = "토큰 갱신",
            description = "refresh 쿠키로 새 access·refresh 를 받는다. 옛 refresh 는 즉시 무효가 된다(회전).")
    @PostMapping("/refresh")
    public ResponseEntity<ApiResponse<MemberResponse>> refresh(HttpServletRequest request) {
        String refreshToken = AuthCookies.read(request, AuthCookies.REFRESH).orElse(null);
        var tokens = authService.refresh(refreshToken);
        return ResponseEntity.ok()
                .headers(authCookies.issue(tokens.accessToken(), tokens.refreshToken()))
                .body(ApiResponse.onSuccess(MemberResponse.from(tokens.member())));
    }

    @Operation(summary = "로그아웃", description = "이 기기의 refresh 를 폐기하고 쿠키를 지운다")
    @PostMapping("/logout")
    public ResponseEntity<ApiResponse<Void>> logout(HttpServletRequest request) {
        authService.logout(AuthCookies.read(request, AuthCookies.REFRESH).orElse(null));
        return ResponseEntity.ok()
                .headers(authCookies.clear())
                .body(ApiResponse.onSuccess());
    }

    @Operation(summary = "내 정보")
    @GetMapping("/me")
    public ApiResponse<MemberResponse> me(@AuthenticationPrincipal AuthenticatedMember member) {
        return ApiResponse.onSuccess(authService.me(member.id()));
    }
}
