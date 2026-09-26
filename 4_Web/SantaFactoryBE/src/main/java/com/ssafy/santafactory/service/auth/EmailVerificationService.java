package com.ssafy.santafactory.service.auth;

import com.ssafy.santafactory.global.config.MailProperties;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Locale;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

/**
 * 가입 전 이메일 인증 (S15P21A106-198). 코드 발급 → 코드 확인 → 인증 토큰 → 가입에서 소비.
 *
 * <p>상태는 전부 Redis 에 TTL 로 둔다 — 만료 정리를 따로 하지 않는다. 코드는 해시로 저장해
 * Redis 가 새어도 코드 자체는 안 보이고, 실패 횟수를 제한해 6자리를 온라인으로 못 훑게 한다.
 *
 * <p>인증 토큰은 "이 이메일이 확인됐다"는 증표다. 가입 요청이 들고 오면 한 번 쓰고 지운다 —
 * 코드를 맞힌 사람만 그 이메일로 가입할 수 있고, 같은 확인으로 두 번 가입할 수 없다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EmailVerificationService {

    private static final String CODE_KEY = "email:code:%s";
    private static final String ATTEMPTS_KEY = "email:code:attempts:%s";
    private static final String COOLDOWN_KEY = "email:code:cooldown:%s";
    private static final String VERIFIED_KEY = "email:verified:%s";

    private static final String SUBJECT = "[SANTA FACTORY] 이메일 인증 코드";

    private final StringRedisTemplate redis;
    private final PasswordEncoder passwordEncoder;
    private final MailProperties properties;
    private final EmailSender emailSender;
    private final SecureRandom random = new SecureRandom();

    /** 코드를 만들어 보낸다. 쿨다운 안에 다시 오면 거부한다 — 발송 폭주와 남의 메일함 도배를 막는다. */
    public void issue(String email) {
        String key = normalize(email);
        Boolean firstInWindow = redis.opsForValue()
                .setIfAbsent(COOLDOWN_KEY.formatted(key), "1", properties.resendCooldown());
        if (!Boolean.TRUE.equals(firstInWindow)) {
            throw new GlobalException(ErrorCode.EMAIL_SEND_TOO_OFTEN);
        }

        String code = "%06d".formatted(random.nextInt(1_000_000));
        redis.opsForValue().set(CODE_KEY.formatted(key), passwordEncoder.encode(code), properties.codeTtl());
        redis.delete(ATTEMPTS_KEY.formatted(key));

        long minutes = properties.codeTtl().toMinutes();
        emailSender.send(email, SUBJECT, """
                SANTA FACTORY 회원가입 인증 코드입니다.

                    %s

                %d분 안에 가입 화면에 입력해 주세요. 요청하지 않으셨다면 이 메일은 무시하셔도 됩니다.
                """.formatted(code, minutes));
        log.info("이메일 인증 코드 발급: email={}", key);
    }

    /** 코드를 확인하고 인증 토큰을 준다. 틀리면 횟수를 세고, 한도를 넘으면 코드를 버린다. */
    public String verify(String email, String code) {
        String key = normalize(email);
        String codeKey = CODE_KEY.formatted(key);
        String attemptsKey = ATTEMPTS_KEY.formatted(key);

        String hash = redis.opsForValue().get(codeKey);
        if (hash == null) {
            throw new GlobalException(ErrorCode.EMAIL_CODE_EXPIRED);
        }
        if (!passwordEncoder.matches(code, hash)) {
            Long attempts = redis.opsForValue().increment(attemptsKey);
            redis.expire(attemptsKey, properties.codeTtl());
            if (attempts != null && attempts >= properties.maxAttempts()) {
                redis.delete(codeKey);
                redis.delete(attemptsKey);
                log.warn("이메일 인증 코드 폐기(실패 {}회): email={}", attempts, key);
                throw new GlobalException(ErrorCode.EMAIL_CODE_EXPIRED);
            }
            throw new GlobalException(ErrorCode.EMAIL_CODE_INVALID);
        }

        redis.delete(codeKey);
        redis.delete(attemptsKey);
        String token = newToken();
        redis.opsForValue().set(VERIFIED_KEY.formatted(key), token, properties.verifiedTtl());
        log.info("이메일 인증 완료: email={}", key);
        return token;
    }

    /** 가입이 들고 온 토큰을 확인하고 지운다. 그 이메일로 발급된 토큰이 아니면 가입을 막는다. */
    public void consume(String email, String token) {
        String verifiedKey = VERIFIED_KEY.formatted(normalize(email));
        String stored = redis.opsForValue().get(verifiedKey);
        if (stored == null || token == null || !MessageDigest.isEqual(
                stored.getBytes(StandardCharsets.UTF_8), token.getBytes(StandardCharsets.UTF_8))) {
            throw new GlobalException(ErrorCode.EMAIL_NOT_VERIFIED);
        }
        redis.delete(verifiedKey);
    }

    /** 테스트가 코드 흐름을 건너뛰고 "확인된 이메일" 상태를 만들 때 쓴다. */
    public static String verifiedKey(String email) {
        return VERIFIED_KEY.formatted(normalize(email));
    }

    private static String normalize(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
    }

    private String newToken() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
