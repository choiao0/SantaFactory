package com.ssafy.santafactory.global.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 메일 발송·이메일 인증 설정 (S15P21A106-198). SMTP 접속값은 {@code spring.mail.*} 에 있다.
 *
 * @param enabled        false 면 실제로 보내지 않고 내용을 로그에 찍는다 — 로컬·테스트에서 SMTP 계정 없이 돈다
 * @param from           발신 주소. Gmail 은 로그인 계정과 같아야 한다
 * @param codeTtl        인증 코드 유효 시간
 * @param verifiedTtl    코드 확인 뒤 가입을 마쳐야 하는 시간. 지나면 코드부터 다시 받는다
 * @param resendCooldown 같은 이메일로 코드를 다시 보낼 수 있는 간격
 * @param maxAttempts    코드 입력 실패 허용 횟수. 넘으면 코드가 폐기된다 — 6자리는 무제한이면 100만 번에 뚫린다
 */
@ConfigurationProperties(prefix = "mail")
public record MailProperties(
        @DefaultValue("false") boolean enabled,
        @DefaultValue("no-reply@santafactory.test") String from,
        @DefaultValue("5m") Duration codeTtl,
        @DefaultValue("30m") Duration verifiedTtl,
        @DefaultValue("60s") Duration resendCooldown,
        @DefaultValue("5") int maxAttempts
) {
}
