package com.ssafy.santafactory.entity.member;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.LocalDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 회원. 고객사 담당자(USER)와 영업 담당자(ADMIN)가 같은 테이블에 있다 — 둘 다 이메일·비밀번호로
 * 로그인하므로 나누면 인증 경로가 두 벌이 된다.
 *
 * <p>{@code company}·{@code phone} 은 B2B 리드 정보다. 견적만 뽑고 연락이 안 되면 서비스가
 * 성립하지 않으므로 가입 시 필수로 받는다. ADMIN 행도 같은 제약을 받아 초기화가 자기 값을 채운다.
 */
@Entity
@Table(name = "Members")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Member {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "member_id")
    private Long id;

    @Column(name = "email", nullable = false, unique = true)
    private String email;

    /** BCrypt 해시. 원문은 어디에도 저장하지 않는다. */
    @Column(name = "password", nullable = false, length = 60)
    private String password;

    @Column(name = "name", nullable = false, length = 50)
    private String name;

    @Column(name = "company", nullable = false, length = 100)
    private String company;

    /** 하이픈을 뗀 숫자만 저장한다 — 안 그러면 010-1234-5678 과 01012345678 이 다른 값이 된다. */
    @Column(name = "phone", nullable = false, length = 20)
    private String phone;

    @Enumerated(EnumType.STRING)
    @Column(name = "role", nullable = false, length = 20)
    private Role role;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    private Member(String email, String password, String name, String company, String phone, Role role) {
        this.email = email;
        this.password = password;
        this.name = name;
        this.company = company;
        this.phone = phone;
        this.role = role;
        this.createdAt = LocalDateTime.now();
    }

    /**
     * 가입으로 만드는 회원. <b>역할을 인자로 받지 않는다</b> — 요청 본문에 {@code "role":"ADMIN"} 을
     * 끼워 넣어 관리자가 되는 길을 원천적으로 막는다.
     */
    public static Member signUp(String email, String encodedPassword, String name, String company, String phone) {
        return new Member(email, encodedPassword, name, company, phone, Role.USER);
    }

    /** 관리자. 가입 API 로는 만들 수 없고 기동 시 초기화만 만든다. */
    public static Member admin(String email, String encodedPassword, String name, String company, String phone) {
        return new Member(email, encodedPassword, name, company, phone, Role.ADMIN);
    }

    public boolean isAdmin() {
        return role == Role.ADMIN;
    }
}
