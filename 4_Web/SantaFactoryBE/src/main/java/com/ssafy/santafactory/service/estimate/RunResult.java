package com.ssafy.santafactory.service.estimate;

/**
 * 판정용으로 정규화한 run 1건.
 *
 * <p>시뮬 KPI 원본이 아니라 조건 판정에 쓰는 값만 담는다. 단위는 DB·ERD 규약을 따라 <b>퍼센트</b>다 —
 * {@code Warehouses.target_throughput}·{@code target_utilization} 이 % 이므로 변환 없이 비교된다.
 * 시뮬 SUMMARY 와의 매핑(0~1 → %)은 이 레코드를 만드는 경계에서 한 번만 한다.
 *
 * @param amrCount           AMR 대수
 * @param throughputPercent  출고 처리율 % — 접수 주문 중 완료 비율 ({@code SimScenarios.throughput})
 * @param utilizationPercent AMR 가동률 % ({@code SimScenarios.utilization})
 * @param cost               총 구축 비용, 원 ({@code SimScenarios.total_cost})
 */
public record RunResult(int amrCount, double throughputPercent, double utilizationPercent, long cost) {
}
