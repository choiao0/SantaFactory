package com.ssafy.santafactory.service.auth;

import com.ssafy.santafactory.dto.auth.LoginRequest;
import com.ssafy.santafactory.dto.auth.MemberResponse;
import com.ssafy.santafactory.dto.auth.SignUpRequest;
import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.global.auth.JwtProvider;
import com.ssafy.santafactory.global.auth.JwtProvider.RefreshClaims;
import com.ssafy.santafactory.global.auth.RefreshTokenBlacklist;
import com.ssafy.santafactory.global.auth.RefreshTokenBlacklist.Reason;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.MemberRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 가입·로그인·갱신·로그아웃. 토큰을 쿠키에 싣는 일은 컨트롤러가 한다. */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    private final MemberRepository memberRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtProvider jwtProvider;
    private final RefreshTokenBlacklist blacklist;

    /** 발급된 토큰 한 벌. */
    public record Tokens(Member member, String accessToken, String refreshToken) {
    }

    @Transactional
    public MemberResponse signUp(SignUpRequest request) {
        if (memberRepository.existsByEmail(request.email())) {
            throw new GlobalException(ErrorCode.EMAIL_ALREADY_USED);
        }
        Member member = memberRepository.save(Member.signUp(
                request.email(),
                passwordEncoder.encode(request.password()),
                request.name(),
                request.company(),
                request.normalizedPhone()));
        log.info("회원가입: memberId={}, company={}", member.getId(), member.getCompany());
        return MemberResponse.from(member);
    }

    /**
     * 로그인. 이메일이 없을 때와 비밀번호가 틀릴 때 <b>같은 오류</b>를 준다 — 구분해서 주면
     * 어떤 이메일이 가입돼 있는지 알려주는 셈이 된다.
     */
    @Transactional(readOnly = true)
    public Tokens login(LoginRequest request) {
        Member member = memberRepository.findByEmail(request.email())
                .filter(found -> passwordEncoder.matches(request.password(), found.getPassword()))
                .orElseThrow(() -> new GlobalException(ErrorCode.INVALID_CREDENTIALS));

        log.info("로그인: memberId={}, role={}", member.getId(), member.getRole());
        return issue(member);
    }

    /**
     * 토큰 갱신 (회전).
     *
     * <p>갱신할 때마다 옛 토큰을 폐기하고 새로 발급한다. 그래서 <b>이미 폐기된 토큰이 다시 오면
     * 복제본이 돌고 있다는 신호</b>다 — 정상 흐름에서는 발급받은 토큰이 한 번만 쓰인다.
     *
     * <p>그때 거부만 하면 <b>늦게 온 쪽만 막힌다.</b> 공격자가 먼저 갱신했다면 피해자가 쫓겨나고
     * 공격자는 최신 토큰으로 계속 쓴다. 그래서 그 회원의 refresh 를 전부 폐기해 둘 다 끊고
     * 비밀번호로 다시 로그인하게 한다 (RFC 9700 권고).
     */
    @Transactional(readOnly = true)
    public Tokens refresh(String refreshToken) {
        RefreshClaims claims = jwtProvider.parseRefresh(refreshToken)
                .orElseThrow(() -> new GlobalException(ErrorCode.REFRESH_TOKEN_INVALID));

        var revoked = blacklist.revokedReason(claims);
        if (revoked.isPresent()) {
            // 회전으로 소비된 토큰이 다시 온 것만 재사용으로 본다. 로그아웃한 토큰이 다시 오는 건
            // 남은 탭이 갱신을 시도하는 정상 상황이라, 그걸로 전체를 끊으면 안 된다
            if (revoked.get() == Reason.ROTATED) {
                log.warn("회전된 refresh 토큰이 다시 왔습니다 — 재사용으로 보고 회원 {} 의 토큰을 전부 폐기합니다",
                        claims.memberId());
                blacklist.revokeAll(claims.memberId());
            }
            throw new GlobalException(ErrorCode.REFRESH_TOKEN_INVALID);
        }

        Member member = memberRepository.findById(claims.memberId())
                .orElseThrow(() -> {
                    // 회원이 지워졌는데 토큰이 남은 경우
                    blacklist.revokeAll(claims.memberId());
                    return new GlobalException(ErrorCode.REFRESH_TOKEN_INVALID);
                });

        blacklist.revoke(claims, Reason.ROTATED);   // 회전 — 쓴 토큰은 즉시 무효
        return issue(member);
    }

    /** 로그아웃 — 이 기기의 refresh 만 폐기한다. 다른 기기 로그인은 유지된다. */
    public void logout(String refreshToken) {
        jwtProvider.parseRefresh(refreshToken)
                .ifPresent(claims -> blacklist.revoke(claims, Reason.LOGGED_OUT));
    }

    @Transactional(readOnly = true)
    public MemberResponse me(Long memberId) {
        return memberRepository.findById(memberId)
                .map(MemberResponse::from)
                .orElseThrow(() -> new GlobalException(ErrorCode.UNAUTHORIZED));
    }

    private Tokens issue(Member member) {
        return new Tokens(member, jwtProvider.issueAccess(member), jwtProvider.issueRefresh(member));
    }
}
