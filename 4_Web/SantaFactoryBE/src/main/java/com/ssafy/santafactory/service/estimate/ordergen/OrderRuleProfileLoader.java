package com.ssafy.santafactory.service.estimate.ordergen;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.Getter;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;

/**
 * {@code classpath:ordergen/order_rules.json}을 앱 시작 시 한 번 읽어 검증하고 보관한다.
 *
 * <p>매 견적마다 파일을 다시 읽지 않도록 빈 생성 시 한 번만 로드한다 — 프로파일은 정적 데이터라
 * 런타임에 바뀌지 않는다.
 */
@Component
public class OrderRuleProfileLoader {

    @Getter
    private final OrderRuleProfile profile;

    public OrderRuleProfileLoader(ObjectMapper objectMapper) {
        this.profile = load(objectMapper);
        validate(this.profile);
    }

    private OrderRuleProfile load(ObjectMapper objectMapper) {
        try (InputStream in = new ClassPathResource("ordergen/order_rules.json").getInputStream()) {
            return objectMapper.readValue(in, OrderRuleProfile.class);
        } catch (IOException e) {
            throw new IllegalStateException("주문 생성 프로파일(order_rules.json)을 읽을 수 없음", e);
        }
    }

    /** 원본 파이썬 검증(_histogram/_curve)과 동일한 최소 불변식만 확인한다. */
    private void validate(OrderRuleProfile profile) {
        requireHistogram(profile.lineCount(), "line_count");
        requireHistogram(profile.quantity(), "quantity");
        if (profile.minuteWeights() == null || profile.minuteWeights().length != 1440) {
            throw new IllegalStateException("minute_weights는 1440칸이어야 함");
        }
        double[][] curve = profile.skuCumulative();
        if (curve == null || curve.length < 2) {
            throw new IllegalStateException("sku_cumulative 곡선이 없음");
        }
        double[] first = curve[0];
        double[] last = curve[curve.length - 1];
        if (first[0] != 0.0 || first[1] != 0.0 || last[0] != 1.0 || last[1] != 1.0) {
            throw new IllegalStateException("sku_cumulative는 (0,0)에서 (1,1)까지여야 함");
        }
        for (int i = 1; i < curve.length; i++) {
            if (curve[i][0] <= curve[i - 1][0] || curve[i][1] < curve[i - 1][1]) {
                throw new IllegalStateException("sku_cumulative는 x가 증가하고 y가 단조 비감소해야 함");
            }
        }
    }

    private void requireHistogram(OrderRuleProfile.Histogram histogram, String label) {
        if (histogram == null || histogram.values() == null || histogram.weights() == null
                || histogram.values().length == 0 || histogram.values().length != histogram.weights().length) {
            throw new IllegalStateException(label + " values/weights 길이가 잘못됨");
        }
    }
}
