package com.ssafy.santafactory.entity.member;

/**
 * 회원 역할. 테이블을 나누지 않고 {@code members.role} 컬럼으로 구분한다 (S15P21A106-186).
 *
 * <p>Spring Security 의 권한 이름은 {@code ROLE_} 접두를 요구하므로 {@link #authority()} 로 만든다.
 */
public enum Role {

    /** 고객사 담당자. 자기 창고·견적만 본다. 가입 API 는 항상 이 역할로 만든다. */
    USER,

    /** Santa Factory 영업. 전체 회원·창고·견적을 본다. 가입으로는 만들 수 없다. */
    ADMIN;

    public String authority() {
        return "ROLE_" + name();
    }
}
