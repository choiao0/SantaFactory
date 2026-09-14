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
 * <p>maxChargers 6 은 시뮬 실행 계약의 {@code --chargers} 상한과 같은 값이고, maxAmrCount 28 은
 * 충전 존이 세울 수 있는 로봇 수다 — 넘기면 시뮬이 배치 단계에서 assert 로 죽는다. 맵에 존이
 * 추가되면 같이 올려야 한다 (출처: 3_FMS/contracts/SIM_RUN_CONTRACT.md §1).
 *
 * @param amrPrice       AMR 대당 단가, 원 ({@code Robots.price})
 * @param chargerPrice   충전기 1대 단가, 원 (미정)
 * @param installPerUnit AMR 1대당 구축·설치비, 원 ({@code Robots.cost})
 * @param maxAmrCount       견적이 시도할 최대 대수 (충전 존 용량, 맵 제약)
 * @param maxChargers    충전기 수 상한
 * @param amrPerCharger  충전기 1대가 감당하는 AMR 수
 * @param amrCountMargin    예산으로 살 수 있는 대수에 더할 여유분
 * @param runTimeout        발행 후 이 시간이 지나도 결과가 없으면 TIMEOUT 처리 (명세 §1-4 는 30분)
 * @param horizon           시뮬 고정 시간 실행 길이. 성능 제약(견적 1회 90초)으로 정해지는 값이라
 *                          창고 데이터가 아니라 설정으로 둔다. 하루 전량으로 바꾸려면 24h
 * @param shifts            입고/출고 교대 토큰열. horizon 을 토큰 수로 등분한다
 * @param verifyWindow      물리 검증(Isaac) 창 길이. SIM_VERIFY_CONTRACT.md 기본값(600s)과 같다
 * @param exportReplay      run 마다 앞 구간 궤적을 함께 받을지 (S15P21A106-205). 워커 시간이 run 당 약
 *                          35 % 늘고 견적당 약 1 MB 를 저장한다. 끄면 대수별 재생 화면이 비어 보인다
 */
@ConfigurationProperties(prefix = "estimate")
public record EstimateProperties(
        @DefaultValue("0") long amrPrice,
        @DefaultValue("0") long chargerPrice,
        @DefaultValue("0") long installPerUnit,
        @DefaultValue("28") int maxAmrCount,
        @DefaultValue("6") int maxChargers,
        @DefaultValue("4") int amrPerCharger,
        @DefaultValue("1") int amrCountMargin,
        @DefaultValue("30m") Duration runTimeout,
        @DefaultValue("6h") Duration horizon,
        @DefaultValue("in,in,out,out,out,out") String shifts,
        @DefaultValue("true") boolean exportReplay,
        @DefaultValue("10m") Duration verifyWindow
) {

    /** 대수에 비례하는 1대당 비용 — 단가 + 구축·설치비. 충전기는 대수의 계단 함수라 여기 넣지 않는다. */
    public long perUnitCost() {
        return amrPrice + installPerUnit;
    }

}
