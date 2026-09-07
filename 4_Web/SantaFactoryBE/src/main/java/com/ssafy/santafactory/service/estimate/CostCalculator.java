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

    /**
     * 총 구축 비용 = (AMR 단가 + 대당 구축·설치비) × 대수 + 충전기 단가 × 충전기 수.
     *
     * <p>{@code Robots.cost}(구축/설치비)가 대당 금액이라 대수에 비례하고, 충전기만 4대마다
     * 하나씩 늘어나는 계단 함수다.
     */
    public long cost(int amrCount) {
        return props.perUnitCost() * amrCount
                + props.chargerPrice() * chargers(amrCount);
    }

    /**
     * 예산 ÷ 대당 비용 + 여유분, 상한 maxAmrCount.
     *
     * <p>충전기 값은 여기 넣지 않는다 — 여유분이 이미 예산을 넘겨 잡는 쪽이고, 예산 초과는
     * 조건 판정에서 대수별 실제 비용으로 다시 걸러진다. 단가가 0(미정)이면 나눌 수 없으므로
     * 상한을 그대로 쓴다.
     */
    public int maxAmrCount(long budget) {
        long perUnit = props.perUnitCost();
        if (perUnit <= 0) {
            return props.maxAmrCount();
        }
        long affordable = Math.max(0, budget) / perUnit;
        return Math.clamp(affordable + props.amrCountMargin(), 1, props.maxAmrCount());
    }
}
