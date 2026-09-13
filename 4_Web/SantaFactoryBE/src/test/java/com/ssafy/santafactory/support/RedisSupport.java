package com.ssafy.santafactory.support;

import org.springframework.boot.test.context.TestComponent;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 테스트 사이에 Redis 를 비운다. refresh 토큰이 남아 있으면 회전·재사용 감지 테스트가 서로 오염된다.
 *
 * <p>Redis 컨테이너 자체는 {@link PostgresSupport} 가 Postgres 와 함께 띄운다 — 컨텍스트 하나에
 * 저장소 두 개가 필요하고, 둘의 수명이 같아서 한곳에 모아 두는 게 단순하다.
 */
@TestComponent
public class RedisSupport {

    private final StringRedisTemplate redis;

    public RedisSupport(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public void flush() {
        redis.getConnectionFactory().getConnection().serverCommands().flushDb();
    }
}
