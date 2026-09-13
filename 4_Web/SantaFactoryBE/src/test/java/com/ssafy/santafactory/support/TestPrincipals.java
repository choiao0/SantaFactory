package com.ssafy.santafactory.support;

import com.ssafy.santafactory.global.auth.AuthenticatedMember;

/**
 * 테스트용 주체. 소유권이 붙은 뒤(S15P21A106-186) 서비스 메서드가 주체를 요구하므로,
 * 소유권이 관심사가 아닌 테스트는 이 값을 쓴다.
 */
public final class TestPrincipals {

    /** 소유권 검사를 통과하는 주체 — ADMIN 은 전체를 볼 수 있어서 창고 주인과 무관하다. */
    public static final AuthenticatedMember ADMIN = new AuthenticatedMember(1L, "ADMIN");

    public static AuthenticatedMember user(Long memberId) {
        return new AuthenticatedMember(memberId, "USER");
    }

    private TestPrincipals() {
    }
}
