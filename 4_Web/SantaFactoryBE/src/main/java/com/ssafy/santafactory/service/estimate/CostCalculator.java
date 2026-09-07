package com.ssafy.santafactory.service.estimate;

import lombok.RequiredArgsConstructor;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

/** 대수 → 비용, 예산 → 최대 대수. 단가는 EstimateProperties 에서 받는다. */
@Component
@RequiredArgsConstructor
@EnableConfigurationProperties(EstimateProperties.class)
public class CostCalculator {

    private final EstimateProperties props;

    /**
     * 이 대수에 필요한 충전기 수.
     * 시뮬 실행 계약의 {@code --chargers} 로도 그대로 넘어가는 값이라 상한을 같이 건다.
     */
    public int chargers(int amrCount) {
        int needed = (amrCount + props.amrPerCharger() - 1) / props.amrPerCharger();
        return Math.min(needed, props.maxChargers());
    }

    /** AMR 단가 + 충전기 + 구축·설치. */
    public long cost(int amrCount) {
        return props.amrPrice() * amrCount
                + props.chargerPrice() * chargers(amrCount)
                + props.installFixed();
    }

    /**
     * 예산 ÷ 대당 비용 + 여유분, 상한 maxFleet.
     * 단가가 0(미정)이면 예산으로 나눌 수 없으므로 상한을 그대로 쓴다.
     */
    public int maxFleet(long budget) {
        if (props.amrPrice() <= 0) {
            return props.maxFleet();
        }
        long affordable = Math.max(0, budget - props.installFixed()) / props.amrPrice();
        return Math.clamp(affordable + props.fleetMargin(), 1, props.maxFleet());
    }
}
