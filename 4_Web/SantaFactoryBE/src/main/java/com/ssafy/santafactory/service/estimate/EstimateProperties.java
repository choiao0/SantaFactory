package com.ssafy.santafactory.service.estimate;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 견적 단가·상한.
 *
 * <p>단가 3개는 아직 팀 미정이라 application.yml 에 0(placeholder)으로 두고, 확정되면
 * yml 만 고친다. maxChargers 6 은 시뮬 실행 계약의 {@code --chargers} 상한과 같은 값이고,
 * maxFleet 8 은 지라 S15P21A106-82 의 상한이다(충전 존 용량 상한 28은 별개 제약).
 *
 * @param amrPrice      AMR 대당 단가 (원)
 * @param chargerPrice  충전기 1대 단가 (원)
 * @param installFixed  구축·설치 고정비 (원)
 * @param maxFleet      견적이 시도할 최대 대수
 * @param maxChargers   충전기 수 상한
 * @param amrPerCharger 충전기 1대가 감당하는 AMR 수
 * @param fleetMargin   예산으로 살 수 있는 대수에 더할 여유분
 */
@ConfigurationProperties(prefix = "estimate")
public record EstimateProperties(
        @DefaultValue("0") long amrPrice,
        @DefaultValue("0") long chargerPrice,
        @DefaultValue("0") long installFixed,
        @DefaultValue("8") int maxFleet,
        @DefaultValue("6") int maxChargers,
        @DefaultValue("4") int amrPerCharger,
        @DefaultValue("1") int fleetMargin
) {
}
