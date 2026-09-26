package com.ssafy.santafactory.entity.estimate;

/**
 * 대수 하나의 물리 검증(Isaac) 회차 상태 (S15P21A106-244). {@link RunStatus} 와 별개다 — DES run 은
 * TIMEOUT 이 있지만 검증은 아직 정리 스윕이 없고, QUEUED 대신 PENDING 을 쓴다.
 */
public enum VerifyRunStatus {

    /** 큐에 발행됨 — 아직 결과 없음. */
    PENDING,

    /** host-orch 가 {@code status: running} 을 보고함. */
    RUNNING,

    /** 결과 {@code status: done} 수신. */
    DONE,

    /** 결과 {@code status: failed} 수신, 또는 그 외 알 수 없는 상태값. */
    FAILED;

    /** 더 이상 결과를 기다리지 않는 상태 — 이게 없으면 검증 중복 요청 가드에 못 걸린다. */
    public boolean isFinished() {
        return this == DONE || this == FAILED;
    }
}
