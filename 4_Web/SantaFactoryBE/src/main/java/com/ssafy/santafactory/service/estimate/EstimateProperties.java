package com.ssafy.santafactory.service.estimate;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 견적 단가·상한.
 *
 * <p>amrPrice·installPerUnit 은 {@code Robots} 시드의 {@code price}(단가)·{@code cost}(구축/설치비)와
 * 같은 값이다 — 둘 다 <b>대당</b> 금액이다. chargerPrice 는 DB·ERD 어디에도 없어 팀 미정이고 0으로 둔다.
 * 확정되면 application.yml 만 고친다.
 *
 * <p>maxChargers 6 은 시뮬 실행 계약의 {@code --chargers} 상한과 같은 값이고, maxFleet 8 은
 * 지라 S15P21A106-82 의 상한이다(충전 존 용량 상한 28은 별개 제약).
 *
 * @param amrPrice       AMR 대당 단가, 원 ({@code Robots.price})
 * @param chargerPrice   충전기 1대 단가, 원 (미정)
 * @param installPerUnit AMR 1대당 구축·설치비, 원 ({@code Robots.cost})
 * @param maxFleet       견적이 시도할 최대 대수
 * @param maxChargers    충전기 수 상한
 * @param amrPerCharger  충전기 1대가 감당하는 AMR 수
 * @param fleetMargin    예산으로 살 수 있는 대수에 더할 여유분
 */
@ConfigurationProperties(prefix = "estimate")
public record EstimateProperties(
        @DefaultValue("0") long amrPrice,
        @DefaultValue("0") long chargerPrice,
        @DefaultValue("0") long installPerUnit,
        @DefaultValue("8") int maxFleet,
        @DefaultValue("6") int maxChargers,
        @DefaultValue("4") int amrPerCharger,
        @DefaultValue("1") int fleetMargin
) {

    /** 대수에 비례하는 1대당 비용 — 단가 + 구축·설치비. 충전기는 대수의 계단 함수라 여기 넣지 않는다. */
    public long perUnitCost() {
        return amrPrice + installPerUnit;
    }
}
