package com.ssafy.santafactory.service.estimate;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.time.Duration;

/**
 * 견적 단가·상한.
 *
 * <p>amrPrice·installPerUnit 은 {@code Robots} 시드의 {@code price}(단가)·{@code cost}(구축/설치비)와
 * 같은 값이다 — 둘 다 <b>대당</b> 금액이다. chargerPrice 는 DB·ERD 어디에도 없어 팀 미정이고 0으로 둔다.
 * 확정되면 application.yml 만 고친다.
 *
 * <p>maxChargers 6 은 시뮬 실행 계약의 {@code --chargers} 상한과 같은 값이고, maxAmrCount 8 은
 * 지라 S15P21A106-82 의 상한이다(충전 존 용량 상한 28은 별개 제약).
 *
 * @param amrPrice       AMR 대당 단가, 원 ({@code Robots.price})
 * @param chargerPrice   충전기 1대 단가, 원 (미정)
 * @param installPerUnit AMR 1대당 구축·설치비, 원 ({@code Robots.cost})
 * @param maxAmrCount       견적이 시도할 최대 대수
 * @param maxChargers    충전기 수 상한
 * @param amrPerCharger  충전기 1대가 감당하는 AMR 수
 * @param amrCountMargin    예산으로 살 수 있는 대수에 더할 여유분
 * @param runTimeout        발행 후 이 시간이 지나도 결과가 없으면 TIMEOUT 처리 (명세 §1-4 는 30분)
 * @param horizon           시뮬 고정 시간 실행 길이. 성능 제약(견적 1회 90초)으로 정해지는 값이라
 *                          창고 데이터가 아니라 설정으로 둔다. 하루 전량으로 바꾸려면 24h
 * @param shifts            입고/출고 교대 토큰열. horizon 을 토큰 수로 등분한다
 */
@ConfigurationProperties(prefix = "estimate")
public record EstimateProperties(
        @DefaultValue("0") long amrPrice,
        @DefaultValue("0") long chargerPrice,
        @DefaultValue("0") long installPerUnit,
        @DefaultValue("8") int maxAmrCount,
        @DefaultValue("6") int maxChargers,
        @DefaultValue("4") int amrPerCharger,
        @DefaultValue("1") int amrCountMargin,
        @DefaultValue("30m") Duration runTimeout,
        @DefaultValue("6h") Duration horizon,
        @DefaultValue("in,in,out,out,out,out") String shifts
) {

    /** 대수에 비례하는 1대당 비용 — 단가 + 구축·설치비. 충전기는 대수의 계단 함수라 여기 넣지 않는다. */
    public long perUnitCost() {
        return amrPrice + installPerUnit;
    }

    /**
     * 시뮬이 출고 주문을 받는 시간(초) — horizon 을 shifts 토큰 수로 등분한 중 out 토큰 몫.
     * 기본값(6h, in,in,out,out,out,out)이면 4시간이다. 실측 출고 건수를 건/일 로 환산할 때 쓴다.
     */
    public long simulatedOutboundSeconds() {
        String[] tokens = shifts == null ? new String[0] : shifts.split(",");
        long outbound = java.util.Arrays.stream(tokens).map(String::trim).filter("out"::equals).count();
        if (tokens.length == 0 || outbound == 0) {
            return horizon.toSeconds();   // 교대를 안 쓰면 전 구간이 출고인 셈으로 본다
        }
        return horizon.toSeconds() * outbound / tokens.length;
    }
}
