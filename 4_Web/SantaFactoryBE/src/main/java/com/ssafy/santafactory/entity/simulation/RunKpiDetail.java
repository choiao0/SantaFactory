package com.ssafy.santafactory.entity.simulation;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * run 하나의 상세 지표 — 명세 §1-2 kpi 중 판정에는 안 쓰지만 견적서·검증 비교에 쓰는 7개 (S15P21A106-236).
 * 시간 단위는 초, 거리는 m, 비율은 0~1 로 시뮬이 준 값 그대로다.
 */
@Embeddable
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RunKpiDetail {

    @Column(name = "orders_total")
    private Integer ordersTotal;

    @Column(name = "orders_completed")
    private Integer ordersCompleted;

    @Column(name = "lead_time_mean_s")
    private Double leadTimeMeanS;

    @Column(name = "queue_time_mean_s")
    private Double queueTimeMeanS;

    @Column(name = "throughput_orders_per_h")
    private Double throughputOrdersPerH;

    @Column(name = "conflict_wait_ratio")
    private Double conflictWaitRatio;

    @Column(name = "distance_total_m")
    private Long distanceTotalM;

    public RunKpiDetail(Integer ordersTotal, Integer ordersCompleted, Double leadTimeMeanS, Double queueTimeMeanS,
                        Double throughputOrdersPerH, Double conflictWaitRatio, Long distanceTotalM) {
        this.ordersTotal = ordersTotal;
        this.ordersCompleted = ordersCompleted;
        this.leadTimeMeanS = leadTimeMeanS;
        this.queueTimeMeanS = queueTimeMeanS;
        this.throughputOrdersPerH = throughputOrdersPerH;
        this.conflictWaitRatio = conflictWaitRatio;
        this.distanceTotalM = distanceTotalM;
    }
}
