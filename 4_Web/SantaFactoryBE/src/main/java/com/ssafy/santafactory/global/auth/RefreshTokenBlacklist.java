package com.ssafy.santafactory.global.auth;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * refresh 토큰 폐기 목록 (Redis).
 *
 * <p><b>블랙리스트 방식</b> — 서명·만료가 유효한 토큰은 기본적으로 통과하고, 여기 담긴 것만
 * 거부한다. 화이트리스트(발급분을 전부 저장)와 비교하면 보관 대상이 "폐기한 것"으로 바뀐다.
 *
 * <p>Redis 를 쓰는 이유는 <b>TTL</b> 이다. 폐기 기록은 그 토큰이 원래 만료될 때까지만 의미가 있다 —
 * 그 뒤엔 JWT 의 {@code exp} 검사에서 어차피 걸린다. RDBMS 면 만료된 행을 지우는 스케줄러를 따로
 * 돌려야 하는데 Redis 는 알아서 지운다.
 *
 * <p>키 두 종류:
 * <pre>
 *   refresh:blacklist:{jti}        → "1"           TTL = 그 토큰의 남은 수명
 *   refresh:notbefore:{memberId}   → epoch millis  TTL = refresh 최대 수명
 * </pre>
 *
 * <p>두 번째가 <b>회원 단위 일괄 폐기</b>다. 토큰을 하나씩 담지 않고 "이 시각 이전 발급분은 전부
 * 무효"라는 기준선 하나만 둔다 — 기기가 몇 대든 키 하나로 끝난다.
 */
@Slf4j
@Component
public class RefreshTokenBlacklist {

    private static final String BLACKLIST_KEY = "refresh:blacklist:%s";
    private static final String NOT_BEFORE_KEY = "refresh:notbefore:%d";

    private final StringRedisTemplate redis;
    private final Duration refreshTtl;

    public RefreshTokenBlacklist(StringRedisTemplate redis, AuthProperties props) {
        this.redis = redis;
        this.refreshTtl = props.refreshTtl();
    }

    /**
     * 폐기 사유. 값으로 저장해 <b>재사용 공격과 정상 로그아웃을 구분</b>한다.
     *
     * <p>구분하지 않으면 로그아웃한 뒤 남은 탭이 갱신을 한 번 시도하는 것만으로 "재사용"으로 몰려
     * 모든 기기가 끊긴다. 사용자는 이유를 알 수 없다.
     */
    public enum Reason {
        /** 갱신으로 소비됨. 이걸 다시 쓰면 복제본이 돌고 있다는 뜻이다. */
        ROTATED,
        /** 사용자가 로그아웃함. 다시 와도 그냥 거부만 한다. */
        LOGGED_OUT
    }

    /**
     * 이 토큰을 폐기한다. 회전(갱신 시 옛 토큰)과 로그아웃이 쓴다.
     *
     * <p>TTL 을 남은 수명으로 잡아, 어차피 만료될 토큰을 계속 들고 있지 않는다. 이미 만료된
     * 토큰이면 담을 이유가 없으므로 건너뛴다.
     */
    public void revoke(JwtProvider.RefreshClaims claims, Reason reason) {
        Duration remaining = Duration.between(Instant.now(), claims.expiresAt());
        if (remaining.isNegative() || remaining.isZero()) {
            return;
        }
        redis.opsForValue().set(BLACKLIST_KEY.formatted(claims.jti()), reason.name(), remaining);
    }

    /** 폐기됐다면 그 사유. 살아 있으면 빈 값. */
    public Optional<Reason> revokedReason(JwtProvider.RefreshClaims claims) {
        if (issuedBeforeCutoff(claims)) {
            // 일괄 폐기는 이미 공격 대응으로 내려진 조치다. 또 전체 폐기를 부를 필요는 없다
            return Optional.of(Reason.LOGGED_OUT);
        }
        String reason = redis.opsForValue().get(BLACKLIST_KEY.formatted(claims.jti()));
        return reason == null ? Optional.empty() : Optional.of(Reason.valueOf(reason));
    }

    /**
     * 그 회원의 refresh 를 전부 폐기한다.
     *
     * <p>재사용이 감지됐을 때 쓴다 — 옛 토큰이 다시 들어왔다는 건 복제본이 돌고 있다는 뜻이고,
     * 그 시점에 공격자와 피해자 중 누가 최신 토큰을 쥐었는지 알 수 없다. 거부만 하면 늦게 온 쪽만
     * 막히므로 <b>둘 다 끊고 비밀번호로 다시 로그인시켜야</b> 확실하다 (RFC 9700 권고).
     *
     * <p>"모든 기기에서 로그아웃"에도 그대로 쓸 수 있다.
     */
    public void revokeAll(Long memberId) {
        redis.opsForValue().set(
                NOT_BEFORE_KEY.formatted(memberId), String.valueOf(Instant.now().toEpochMilli()), refreshTtl);
        log.warn("회원 {} 의 refresh 토큰을 전부 폐기했습니다", memberId);
    }

    /** 일괄 폐기 기준선보다 먼저 발급된 토큰인가. */
    private boolean issuedBeforeCutoff(JwtProvider.RefreshClaims claims) {
        String cutoff = redis.opsForValue().get(NOT_BEFORE_KEY.formatted(claims.memberId()));
        if (cutoff == null) {
            return false;
        }
        // 발급 시각은 초 단위로 잘려 저장되므로(JWT iat 규격) 같은 초에 발급된 토큰이 살아남지
        // 않도록 기준선 이하를 모두 무효로 본다
        return !claims.issuedAt().isAfter(Instant.ofEpochMilli(Long.parseLong(cutoff)));
    }
}
