package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.VerifyNoticeCode;
import org.junit.jupiter.api.Test;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.spring6.SpringTemplateEngine;
import org.thymeleaf.templatemode.TemplateMode;
import org.thymeleaf.templateresolver.ClassLoaderTemplateResolver;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 템플릿이 스프링 없이도 렌더되는지, 두 쪽이 나오는지. 결과 HTML 을 {@code build/quote-preview.html} 에 남겨
 * 브라우저로 모양을 확인할 수 있게 한다.
 */
class QuoteTemplateTest {

    private static TemplateEngine engine() {
        ClassLoaderTemplateResolver resolver = new ClassLoaderTemplateResolver();
        resolver.setPrefix("templates/");
        resolver.setSuffix(".html");
        resolver.setTemplateMode(TemplateMode.HTML);
        resolver.setCharacterEncoding(StandardCharsets.UTF_8.name());
        TemplateEngine engine = new SpringTemplateEngine();   // 운영과 같이 SpEL 로 식을 푼다(OGNL 미포함)
        engine.setTemplateResolver(resolver);
        return engine;
    }

    private final QuoteDocumentFactory factory = new QuoteDocumentFactory(QuoteFixtures.PROPS, QuoteFixtures.PDF);
    private final QuotePdfService service = new QuotePdfService(null, factory, engine(), mock(GotenbergClient.class), QuoteFixtures.PDF);

    @Test
    void renders_two_pages_with_every_block() throws Exception {
        QuoteDocument q = factory.build(new QuoteSource(
                QuoteFixtures.detail(142L, 14, 15, QuoteFixtures.verification(VerifyNoticeCode.SLOWER_AT_PEAK, QuoteFixtures.slowerAtPeak())),
                QuoteFixtures.warehouse()));

        String html = service.html(q);
        Path out = Path.of("build", "quote-preview.html");
        Files.createDirectories(out.getParent());
        Files.writeString(out, html, StandardCharsets.UTF_8);

        assertThat(html).contains("EST-20260917-0142").contains("id=\"p1\"").contains("id=\"p2\"");
        for (String block : new String[]{"발행 정보", "권장 구성", "목표 달성 여부 (14대 기준)", "예상 구축 비용",
                "권장 구성 물리 검증 결과 (3D 시뮬레이션)", "로봇 대수별 비교", "효율과 구축 비용 그래프", "주문 처리율과 구축 비용 그래프", "권장 구성(14대)의 운영 예상", "유의 사항"}) {
            assertThat(html).contains(block);
        }
        assertThat(html).contains(">06</span>").contains(">10</span>");
        assertThat(html).doesNotContain(" th:").doesNotContain("${");
        assertThat(html).contains("data:image/png;base64,");
    }

    @Test
    void renders_without_a_recommendation_and_renumbers_the_appendix() {
        var d = QuoteFixtures.detail(9L, null, null, null);
        var noRec = new com.ssafy.santafactory.dto.estimate.EstimateDetailResponse(d.estimateId(), d.status(), d.amrModel(),
                d.targetThroughput(), d.targetUtilization(), d.budgetLimit(), null, null, null,
                com.ssafy.santafactory.entity.estimate.ReasonCode.THROUGHPUT_SHORT, d.createdAt(), d.completedAt(), d.elapsedSeconds(),
                null, null, d.runs(), null);

        String html = service.html(factory.build(new QuoteSource(noRec, QuoteFixtures.warehouse())));

        assertThat(html).contains("목표 주문 처리율에 닿지 않습니다").doesNotContain("금액 (원)").doesNotContain("목표 달성 여부").contains(">03</span>").contains(">07</span>");
    }
}
