package com.ssafy.santafactory.service.estimate.ordergen;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * 출고 주문 생성 통계 프로파일 — {@code 3_FMS/order_gen/profiles/order_rules.json}을 그대로 옮긴 리소스의
 * 매핑이다. 외부 데이터셋(신발 물류센터 피킹 로그)에서 한 번 뽑아낸 정적 값이라 자주 바뀌지 않는다.
 *
 * <p>{@code abc_ratios}·{@code source}·{@code stats}·{@code summary}는 원본에서도 진단용 메타데이터일
 * 뿐 추첨 가중치엔 안 쓰여서 여기 옮기지 않는다({@code @JsonIgnoreProperties}로 무시).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record OrderRuleProfile(
        Histogram lineCount,
        Histogram quantity,
        int[] minuteWeights,
        double[][] skuCumulative
) {

    /** 정수 값과 그 가중치의 병렬 배열. 값은 오름차순·중복 없음이 전제다. */
    public record Histogram(int[] values, double[] weights) {
    }
}
