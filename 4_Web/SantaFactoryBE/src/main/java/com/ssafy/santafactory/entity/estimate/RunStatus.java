package com.ssafy.santafactory.entity.estimate;

/** 대수별 시뮬 실행 1건의 상태. 시뮬 엔진 연동 API 명세 §3-4. */
public enum RunStatus {

    /** 요청 큐에 발행됨. */
    QUEUED,

    /** 워커가 꺼내 계산 중 — 결과 큐의 {@code status: running} 수신. */
    RUNNING,

    /** 결과 메시지 {@code status: done} 수신. */
    DONE,

    /** 결과 메시지 {@code status: failed} 수신, 또는 발행 실패. */
    FAILED,

    /** 정해진 시간 안에 결과가 오지 않음. */
    TIMEOUT;

    /** 더 이상 결과를 기다리지 않는 상태 — 중복 결과 무시 판단에 쓴다. */
    public boolean isFinished() {
        return this == DONE || this == FAILED || this == TIMEOUT;
    }
}
