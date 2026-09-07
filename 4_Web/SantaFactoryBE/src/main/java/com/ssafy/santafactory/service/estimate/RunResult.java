package com.ssafy.santafactory.service.estimate;

/**
 * 판정용으로 정규화한 run 1건.
 *
 * <p>시뮬 KPI 원본이 아니라 조건 판정에 쓰는 값만 담는다. 시뮬 SUMMARY 와의 매핑은
 * 이 레코드를 만드는 경계(결과 수신)에서 한 번만 한다:
 * {@code orders_per_h → ordersPerH}, {@code util_incl_service → utilization}.
 */
public record RunResult(int amrCount, double ordersPerH, double utilization, long cost) {
}
