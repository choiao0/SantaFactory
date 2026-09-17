package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/**
 * 견적서 HTML → PDF. compose 의 {@code pdf} 서비스(Gotenberg)에 multipart 로 보낸다 (S15P21A106-236).
 *
 * <p>변환은 한 번에 하나만 보낸다 — 크로미움이 건당 300 MB 안팎을 쓰고 서버가 4 GB 라, 동시에 여러 건이 몰리면
 * 변환기가 아니라 옆 컨테이너가 밀린다. 순서를 기다리다 타임아웃이면 503 으로 돌려 다시 누르게 한다.
 */
@Slf4j
@Component
@EnableConfigurationProperties(QuotePdfProperties.class)
public class GotenbergClient {

    private static final String CONVERT_HTML = "/forms/chromium/convert/html";

    private final QuotePdfProperties props;
    private final RestClient client;
    private final Semaphore oneAtATime = new Semaphore(1);

    @Autowired
    public GotenbergClient(QuotePdfProperties props) {
        this(props, RestClient.builder());
    }

    GotenbergClient(QuotePdfProperties props, RestClient.Builder builder) {
        this.props = props;
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(java.time.Duration.ofSeconds(5));
        factory.setReadTimeout(props.timeout());
        this.client = builder.baseUrl(props.available() ? props.baseUrl() : "http://pdf-disabled")
                .requestFactory(factory).build();
    }

    /** A4 세로, 여백 0, 배경색 인쇄. 템플릿의 {@code @page} 크기를 그대로 쓴다. */
    public byte[] htmlToPdf(String html) {
        if (!props.available()) {
            throw new GlobalException(ErrorCode.QUOTE_PDF_UNAVAILABLE);
        }
        boolean acquired;
        try {
            acquired = oneAtATime.tryAcquire(props.timeout().toMillis(), TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new GlobalException(ErrorCode.QUOTE_PDF_UNAVAILABLE);
        }
        if (!acquired) {
            log.warn("PDF 변환 대기 초과 — 다른 변환이 {} 넘게 잡고 있음", props.timeout());
            throw new GlobalException(ErrorCode.QUOTE_PDF_UNAVAILABLE);
        }
        try {
            byte[] pdf = client.post().uri(CONVERT_HTML)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .accept(MediaType.APPLICATION_PDF)
                    .body(form(html))
                    .retrieve()
                    .body(byte[].class);
            if (pdf == null || pdf.length == 0) {
                throw new GlobalException(ErrorCode.QUOTE_PDF_UNAVAILABLE);
            }
            return pdf;
        } catch (RestClientException e) {
            log.error("PDF 변환 실패: {}", e.toString());
            throw new GlobalException(ErrorCode.QUOTE_PDF_UNAVAILABLE);
        } finally {
            oneAtATime.release();
        }
    }

    private static MultiValueMap<String, Object> form(String html) {
        MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
        form.add("files", new ByteArrayResource(html.getBytes(StandardCharsets.UTF_8)) {
            @Override
            public String getFilename() {
                return "index.html";
            }
        });
        form.add("paperWidth", "8.27");
        form.add("paperHeight", "11.69");
        form.add("marginTop", "0");
        form.add("marginBottom", "0");
        form.add("marginLeft", "0");
        form.add("marginRight", "0");
        form.add("printBackground", "true");
        form.add("preferCssPageSize", "true");
        return form;
    }
}
