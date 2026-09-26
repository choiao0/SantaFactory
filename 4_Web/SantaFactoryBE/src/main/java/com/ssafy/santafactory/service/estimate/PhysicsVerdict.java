package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.simulation.PhysicsMetrics;
import com.ssafy.santafactory.entity.estimate.VerifyRunStatus;

/**
 * 물리 판정 규칙 — 명세 §D, 화면·견적서 공통으로 한 곳에서만 계산한다 (S15P21A106-244).
 *
 * <ul>
 *   <li>PASS — 로봇·랙 접촉이 없고, 창 안 계획 동작 중 시작한 비율이 0.80 이상
 *   <li>WARN — 접촉은 없지만 비율이 0.80 미만 (DES 계획을 물리가 제때 못 따라감 — 지연)
 *   <li>FAIL — 접촉이 있거나, 검증 자체가 실패(status failed)
 *   <li>N/A  — {@code window_actions} 가 없음(구간 재생이 아니었거나 physics 를 못 받음)
 * </ul>
 */
public final class PhysicsVerdict {

    /** 창 안 계획 동작 중 시작한 비율의 통과선. */
    /** 적합 기준 — 견적서 보고서의 판정 설명도 이 값을 쓴다 (S15P21A106-280). */
    public static final double PASS_RATIO = 0.80;

    private PhysicsVerdict() {
    }

    public enum Verdict {
        PASS, WARN, FAIL, NA
    }

    public static Verdict of(VerifyRunStatus status, PhysicsMetrics physics) {
        if (status == VerifyRunStatus.FAILED) {
            return Verdict.FAIL;
        }
        if (physics == null || physics.windowActions() == null) {
            return Verdict.NA;
        }
        if (hasContact(physics.robotContacts()) || hasContact(physics.rackContacts())) {
            return Verdict.FAIL;
        }
        Double ratio = physics.windowActions().ratio();
        if (ratio == null) {
            return Verdict.NA;
        }
        return ratio >= PASS_RATIO ? Verdict.PASS : Verdict.WARN;
    }

    private static boolean hasContact(Integer contacts) {
        return contacts != null && contacts > 0;
    }
}
