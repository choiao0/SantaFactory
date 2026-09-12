package com.ssafy.santafactory.global.auth;

import com.ssafy.santafactory.entity.member.Member;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.Optional;
import java.util.UUID;
import javax.crypto.SecretKey;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * access·refresh 토큰 발급과 검증. HS256 대칭키를 쓴다 — 발급자와 검증자가 같은 서비스라
 * 비대칭키가 필요 없다.
 *
 * <p><b>두 토큰을 같은 키로 서명하므로 종류를 클레임으로 구분한다.</b> 안 하면 access 토큰을
 * 갱신 요청에 들이밀 수 있다 — 서명도 만료도 유효하니 그대로 통과해 버린다.
 *
 * <p>refresh 에는 {@code jti}(토큰 고유 id)를 넣는다. 폐기를 블랙리스트로 하므로
 * ({@link RefreshTokenBlacklist}) 토큰마다 식별자가 필요하다.
 */
@Slf4j
@Component
public class JwtProvider {

    /** HS256 최소 키 길이. 짧으면 jjwt 가 기동 시 예외를 던진다. */
    private static final int MIN_SECRET_BYTES = 32;

    private static final String CLAIM_ROLE = "role";
    private static final String CLAIM_TYPE = "typ";
    private static final String TYPE_ACCESS = "access";
    private static final String TYPE_REFRESH = "refresh";

    private final SecretKey key;
    private final Duration accessTtl;
    private final Duration refreshTtl;

    public JwtProvider(AuthProperties props) {
        byte[] secret = props.secret() == null ? new byte[0] : props.secret().getBytes(StandardCharsets.UTF_8);
        if (secret.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "auth.secret 이 너무 짧습니다 (%d 바이트). HS256 은 %d 바이트 이상이 필요합니다 — openssl rand -base64 48"
                            .formatted(secret.length, MIN_SECRET_BYTES));
        }
        this.key = Keys.hmacShaKeyFor(secret);
        this.accessTtl = props.accessTtl();
        this.refreshTtl = props.refreshTtl();
    }

    /** 회원 → access 토큰. 역할을 클레임에 실어 DB 조회 없이 권한을 판단한다. */
    public String issueAccess(Member member) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(String.valueOf(member.getId()))
                .claim(CLAIM_TYPE, TYPE_ACCESS)
                .claim(CLAIM_ROLE, member.getRole().name())
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(accessTtl)))
                .signWith(key)
                .compact();
    }

    /** 회원 → refresh 토큰. 역할은 담지 않는다 — 갱신할 때 DB 에서 다시 읽으므로 낡을 여지를 없앤다. */
    public String issueRefresh(Member member) {
        Instant now = Instant.now();
        return Jwts.builder()
                .id(UUID.randomUUID().toString())       // jti — 폐기 단위
                .subject(String.valueOf(member.getId()))
                .claim(CLAIM_TYPE, TYPE_REFRESH)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(refreshTtl)))
                .signWith(key)
                .compact();
    }

    /**
     * access 토큰 검증.
     *
     * <p>실패를 예외로 던지지 않고 빈 값으로 준다 — 만료는 정상 흐름(프론트가 refresh 로 갱신)이라
     * 예외로 다루면 로그가 쓸데없이 시끄러워진다.
     */
    public Optional<AuthenticatedMember> parseAccess(String token) {
        return parse(token, TYPE_ACCESS)
                .map(claims -> new AuthenticatedMember(
                        Long.valueOf(claims.getSubject()), claims.get(CLAIM_ROLE, String.class)));
    }

    /** refresh 토큰 검증. access 토큰을 넣으면 종류가 달라 거부된다. */
    public Optional<RefreshClaims> parseRefresh(String token) {
        return parse(token, TYPE_REFRESH)
                .map(claims -> new RefreshClaims(
                        claims.getId(),
                        Long.valueOf(claims.getSubject()),
                        claims.getIssuedAt().toInstant(),
                        claims.getExpiration().toInstant()));
    }

    private Optional<Claims> parse(String token, String expectedType) {
        if (token == null || token.isBlank()) {
            return Optional.empty();
        }
        try {
            Claims claims = Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
            String type = claims.get(CLAIM_TYPE, String.class);
            if (!expectedType.equals(type)) {
                log.warn("토큰 종류가 다릅니다: 기대 {}, 실제 {}", expectedType, type);
                return Optional.empty();
            }
            return Optional.of(claims);
        } catch (JwtException | IllegalArgumentException e) {
            log.debug("{} 토큰 검증 실패: {}", expectedType, e.getMessage());
            return Optional.empty();
        }
    }

    /**
     * refresh 토큰에서 꺼낸 값.
     *
     * @param jti       토큰 고유 id — 블랙리스트의 키
     * @param memberId  주체
     * @param issuedAt  발급 시각 — 회원 단위 일괄 폐기({@code notBefore}) 판정에 쓴다
     * @param expiresAt 만료 시각 — 블랙리스트 항목의 TTL 을 여기서 구한다
     */
    public record RefreshClaims(String jti, Long memberId, Instant issuedAt, Instant expiresAt) {
    }
}
