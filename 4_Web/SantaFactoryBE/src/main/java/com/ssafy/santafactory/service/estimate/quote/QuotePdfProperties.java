package com.ssafy.santafactory.service.estimate.quote;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.time.Duration;

/**
 * 견적서 PDF 변환기 연결 (S15P21A106-236).
 *
 * @param baseUrl 변환기(Gotenberg) 주소. 비어 있으면 변환기가 없는 환경이라 견적서 API 가 503 을 준다
 * @param timeout 변환 1건의 응답 대기 상한
 * @param siteUrl 견적서에 적는 서비스 공개 주소(웹에서 견적 열어 보기 링크)
 */
@ConfigurationProperties(prefix = "pdf")
public record QuotePdfProperties(
        @DefaultValue("") String baseUrl,
        @DefaultValue("30s") Duration timeout,
        @DefaultValue("http://localhost:5173") String siteUrl
) {

    public boolean available() {
        return baseUrl != null && !baseUrl.isBlank();
    }
}
