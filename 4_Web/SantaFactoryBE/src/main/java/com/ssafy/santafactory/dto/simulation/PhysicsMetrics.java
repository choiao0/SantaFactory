package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * {@code sim.verify.result.physics} — 러너 {@code Runner/Physics} 를 host-orch 가 파싱한 객체
 * (3_FMS/contracts/SIM_VERIFY_CONTRACT.md v0.5, S15P21A106-244). 구간 재생이 아니면
 * {@code lag}·{@code windowActions}·{@code desWindow} 가 null 이다 — 그때 물리 판정은 {@code N/A} 다
 * ({@link com.ssafy.santafactory.service.estimate.PhysicsVerdict}).
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@JsonIgnoreProperties(ignoreUnknown = true)
public record PhysicsMetrics(
        String engine,
        Integer nRobots,
        Double simS,
        Double windowSimS,
        Double warmupS,
        Double windowS,
        Double wallS,
        Double rtf,
        Integer robotContacts,
        Double robotMinGapM,
        Integer rackContacts,
        Double rackWorstPenMm,
        Integer zoneIntrusions,
        Double zoneWorstPenMm,
        Integer stallSteps,
        Integer turnGaveup,
        Integer recoverEvents,
        Integer cellOverlaps,
        Integer actionsStarted,
        Integer actionsCompleted,
        Lag lag,
        WindowActions windowActions,
        Blocked blocked,
        DesWindow desWindow
) {

    /** 구간 재생 창의 지연 분포. 구간 재생이 아니면 null. */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Lag(Integer n, Double p50S, Double p90S, Double maxS, Double meanS, Double lateRatio) {
    }

    /** DES 계획 대비 물리가 창 안에서 실제로 시작한 동작 비율. 판정 규칙 D 의 핵심 지표. */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record WindowActions(Integer planned, Integer started, Double ratio, Double overdueS) {
    }

    /** 로봇이 멈춰 있던 이유별 프레임 수. */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Blocked(Long robotFrames, Long obstacle, Long release, Long adgSelf, Long adgOther, Double ratio) {
    }

    /** 같은 창의 DES 쪽 수치 — 비교용. */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record DesWindow(Integer tasksDone, Integer moves, Integer turns, Integer reverses) {
    }
}
