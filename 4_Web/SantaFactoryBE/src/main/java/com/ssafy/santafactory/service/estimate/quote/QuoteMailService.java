package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.repository.MemberRepository;
import com.ssafy.santafactory.service.auth.EmailSender;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

/**
 * 견적서를 요청한 계정의 이메일로 보낸다 (S15P21A106-236, 결정: 수신자는 로그인 계정 고정).
 * 컨트롤러가 {@link QuotePdfService#checkRenderable} 로 먼저 걸러 202 를 준 뒤 여기서 만들어 보낸다.
 * 실패는 로그로만 남는다 — 사용자는 다시 누르면 된다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QuoteMailService {

    private final QuotePdfService pdfService;
    private final MemberRepository memberRepository;
    private final EmailSender emailSender;

    @Async
    public void sendToRequester(QuoteSource source, AuthenticatedMember me) {
        Long estimateId = source.detail().estimateId();
        try {
            Member member = memberRepository.findById(me.id()).orElse(null);
            if (member == null) {
                log.warn("견적서 메일 생략 — 회원 없음: memberId={}, estimateId={}", me.id(), estimateId);
                return;
            }
            QuotePdfService.QuotePdf pdf = pdfService.render(source);
            String subject = "[SANTA FACTORY] AMR 도입 견적서 " + pdf.fileName().replace("견적서_", "").replace(".pdf", "");
            String text = """
                    안녕하세요, %s님.

                    요청하신 AMR 도입 견적서를 첨부합니다.
                    권장 로봇 대수와 산정 근거는 첨부 문서에서 확인하실 수 있습니다.

                    이 문서는 시뮬레이션 결과를 바탕으로 한 참고 자료이며 확정 견적이 아닙니다.

                    SANTA FACTORY 드림
                    """.formatted(member.getName());
            emailSender.sendWithAttachment(member.getEmail(), subject, text, pdf.fileName(), pdf.bytes(), "application/pdf");
        } catch (RuntimeException e) {
            log.error("견적서 메일 실패: estimateId={}, memberId={}", estimateId, me.id(), e);
        }
    }
}
