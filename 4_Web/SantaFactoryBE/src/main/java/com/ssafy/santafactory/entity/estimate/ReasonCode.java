package com.ssafy.santafactory.entity.estimate;

/** 권장 대수를 내지 못한 사유. */
public enum ReasonCode {

    /** 모든 대수가 예산을 넘는다. */
    BUDGET_EXCEEDED,

    /** 예산 안에 드는 대수는 있으나, 목표 처리량에 닿는 대수가 없다. */
    THROUGHPUT_SHORT,

    /** 목표 처리량은 채우지만 그 대수의 가동률이 목표에 못 미친다. */
    UTILIZATION_SHORT,

    /** 시뮬이 전 대수 실패해 판정할 결과가 하나도 없다. */
    ALL_FAILED
}
