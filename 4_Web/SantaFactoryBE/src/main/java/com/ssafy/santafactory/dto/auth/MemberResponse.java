package com.ssafy.santafactory.dto.auth;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.member.Role;
import java.time.LocalDateTime;

/** 내 정보. 비밀번호는 어떤 응답에도 담지 않는다. */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record MemberResponse(
        Long memberId,
        String email,
        String name,
        String company,
        String phone,
        Role role,
        LocalDateTime createdAt
) {

    public static MemberResponse from(Member member) {
        return new MemberResponse(
                member.getId(), member.getEmail(), member.getName(),
                member.getCompany(), member.getPhone(), member.getRole(), member.getCreatedAt());
    }
}
