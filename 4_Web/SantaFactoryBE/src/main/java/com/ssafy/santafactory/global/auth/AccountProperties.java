package com.ssafy.santafactory.global.auth;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 주입할 계정 설정 ({@link AccountInitializer}).
 *
 * <p>비밀번호만 환경변수에서 오고 나머지는 yml 에 보이는 값이다 — 비밀이 아니고, 뭘 만들지
 * 한눈에 보이는 쪽이 낫다. 비밀번호가 비면 그 계정을 만들지 않는다.
 */
@ConfigurationProperties(prefix = "account")
public record AccountProperties(Account admin, Account user) {

    /**
     * @param password 비면 계정을 만들지 않는다
     */
    public record Account(String email, String password, String name, String company, String phone) {
    }
}
