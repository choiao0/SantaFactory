package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.member.Role;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MemberRepository extends JpaRepository<Member, Long> {

    /** 로그인·JWT 검증에서 쓴다. */
    Optional<Member> findByEmail(String email);

    /** 가입 시 이메일 중복 검사. */
    boolean existsByEmail(String email);

    /** 계정 초기화가 관리자를 이미 만들었는지 확인한다. */
    boolean existsByRole(Role role);

    /** 관리자 화면 — 회사·이름순 목록. */
    List<Member> findAllByOrderByCompanyAscNameAsc();
}
