package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.service.estimate.EstimateService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;

import java.util.Arrays;
import java.util.Locale;
import java.util.Objects;

/**
 * 견적서 PDF 만들기 (S15P21A106-236). DB 읽기는 {@link EstimateService#quoteSource} 한 번으로 끝내고,
 * 템플릿 렌더와 변환기 호출은 트랜잭션 밖에서 한다 — 변환에 수십 초가 걸려도 커넥션을 잡고 있지 않게.
 */
@Service
@RequiredArgsConstructor
public class QuotePdfService {

    private static final String TEMPLATE = "quote/quote";

    private final EstimateService estimateService;
    private final QuoteDocumentFactory factory;
    private final TemplateEngine templateEngine;
    private final GotenbergClient gotenberg;
    private final QuotePdfProperties props;

    /** 만들어진 PDF. 배열은 내용으로 비교하고, 출력에는 크기만 남긴다. */
    public record QuotePdf(String fileName, byte[] bytes) {

        @Override
        public boolean equals(Object o) {
            return o instanceof QuotePdf other && Objects.equals(fileName, other.fileName) && Arrays.equals(bytes, other.bytes);
        }

        @Override
        public int hashCode() {
            return 31 * Objects.hashCode(fileName) + Arrays.hashCode(bytes);
        }

        @Override
        public String toString() {
            return "QuotePdf[" + fileName + ", " + (bytes == null ? 0 : bytes.length) + " bytes]";
        }
    }

    /** 만들 수 있는 견적인지만 확인한다 — 메일 요청을 202 로 받기 전에 404·409·503 을 바로 돌려주기 위해. */
    public QuoteSource checkRenderable(Long estimateId, AuthenticatedMember me) {
        if (!props.available()) {
            throw new GlobalException(ErrorCode.QUOTE_PDF_UNAVAILABLE);
        }
        QuoteSource source = estimateService.quoteSource(estimateId, me);
        EstimateStatus status = source.detail().status();
        if (status != EstimateStatus.DONE && status != EstimateStatus.PARTIAL) {
            throw new GlobalException(ErrorCode.ESTIMATE_NOT_FINISHED);
        }
        return source;
    }

    public QuotePdf render(Long estimateId, AuthenticatedMember me) {
        return render(checkRenderable(estimateId, me));
    }

    public QuotePdf render(QuoteSource source) {
        QuoteDocument document = factory.build(source);
        return new QuotePdf(document.fileName(), gotenberg.htmlToPdf(html(document)));
    }

    String html(QuoteDocument document) {
        Context context = new Context(Locale.KOREA);
        context.setVariable("q", document);
        return templateEngine.process(TEMPLATE, context);
    }
}
