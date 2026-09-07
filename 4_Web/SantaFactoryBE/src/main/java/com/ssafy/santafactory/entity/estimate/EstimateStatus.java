package com.ssafy.santafactory.entity.estimate;

/** 견적 진행 상태. 시뮬 엔진 연동 API 명세 §3-4. */
public enum EstimateStatus {

    /** 미완료 run 이 하나 이상 남아 있다. */
    RUNNING,

    /** 모든 run 이 DONE. */
    DONE,

    /** 일부 run 이 FAILED/TIMEOUT 이지만 나머지로 판정했다. */
    PARTIAL,

    /** 사용자 취소. 이후 도착하는 결과는 무시한다. */
    CANCELLED
}
