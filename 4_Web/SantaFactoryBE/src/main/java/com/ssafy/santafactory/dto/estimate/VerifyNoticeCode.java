package com.ssafy.santafactory.dto.estimate;

/**
 * 물리 검증 결과를 계산 결과와 견줘 본 판정 (S15P21A106-236). 문구는 화면·견적서가 붙인다({@link ReasonCode} 와 같은 방식).
 * 어느 값이 나와도 권장 대수 판정은 바뀌지 않는다 — 판정은 계산 결과로만 한다.
 */
public enum VerifyNoticeCode {

    /** 검증이 정상 종료되지 않았다(failed, 또는 창이 끝나기 전에 멈춤). 비교표 없음. */
    NOT_FINISHED,

    /** 계산과 다른 조건에서 돌았다(fms.warnings). 수치를 비교하지 않는다. 비교표 없음. */
    DIFFERENT_CONDITIONS,

    /** 견줄 값이 없다 — 권장 run 의 상세 지표나 검증 지표가 없다. 비교표 없음. */
    NO_BASELINE,

    /** 로봇 일부만 가동됐다. 비교표는 보여 주되 참고용이다. */
    PARTIAL_FLEET,

    /** 피크 구간에서 주문 처리 시간 또는 통로 혼잡이 계산보다 기준 이상 나빴다. */
    SLOWER_AT_PEAK,

    /** 계산과 물리 검증이 기준 안에서 일치한다. */
    MATCHES
}
