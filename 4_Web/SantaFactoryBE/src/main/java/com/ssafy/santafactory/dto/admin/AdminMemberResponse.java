package com.ssafy.santafactory.dto.admin;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.member.Role;
import java.time.LocalDateTime;

/**
 * 관리자 화면의 회원 목록 한 행.
 *
 * <p>연락처를 담는다 — 영업이 견적을 낸 담당자에게 연락하는 게 이 화면의 목적이다. 다만 목록에
 * 필요 이상을 싣지 않으려 비밀번호는 물론이고 어떤 인증 정보도 담지 않는다.
 *
 * @param warehouseCount 등록한 창고 수
 * @param estimateCount  요청한 견적 수 — 이 둘로 "활성 고객"이 한눈에 보인다
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AdminMemberResponse(
        Long memberId,
        String email,
        String name,
        String company,
        String phone,
        Role role,
        long warehouseCount,
        long estimateCount,
        LocalDateTime createdAt
) {

    public static AdminMemberResponse of(Member member, long warehouseCount, long estimateCount) {
        return new AdminMemberResponse(
                member.getId(), member.getEmail(), member.getName(), member.getCompany(),
                member.getPhone(), member.getRole(), warehouseCount, estimateCount, member.getCreatedAt());
    }
}
