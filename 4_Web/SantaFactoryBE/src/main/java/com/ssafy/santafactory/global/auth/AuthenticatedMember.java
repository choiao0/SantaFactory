package com.ssafy.santafactory.global.auth;

/**
 * 인증된 요청의 주체. access 토큰 클레임에서 복원하므로 DB 조회가 없다.
 *
 * @param id   회원 id
 * @param role {@code USER} | {@code ADMIN}
 */
public record AuthenticatedMember(Long id, String role) {

    public boolean isAdmin() {
        return "ADMIN".equals(role);
    }
}
