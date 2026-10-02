package com.ssafy.santafactory.support;

import com.ssafy.santafactory.global.auth.AccountProperties;
import com.ssafy.santafactory.global.auth.TrialMode;
import com.ssafy.santafactory.global.auth.TrialProperties;

/** 체험 모드 스위치 (S15P21A106-283). 데모 회원 이메일은 yml 의 account.user.email 자리다. */
public final class TrialFixtures {

    public static final String DEMO_EMAIL = "demo@santafactory.test";

    /** 운영 기본 — 지금까지와 똑같이 동작한다. */
    public static TrialMode off() {
        return new TrialMode(new TrialProperties(false), accounts(DEMO_EMAIL));
    }

    public static TrialMode on() {
        return new TrialMode(new TrialProperties(true), accounts(DEMO_EMAIL));
    }

    /** 체험 모드인데 데모 회원 설정이 없다 — 막기만 하고 공유할 견적은 없다. */
    public static TrialMode onWithoutDemoAccount() {
        return new TrialMode(new TrialProperties(true), new AccountProperties(null, null));
    }

    private static AccountProperties accounts(String demoEmail) {
        return new AccountProperties(null, new AccountProperties.Account(demoEmail, null, "김담당", "품고물류", null));
    }

    private TrialFixtures() {
    }
}
