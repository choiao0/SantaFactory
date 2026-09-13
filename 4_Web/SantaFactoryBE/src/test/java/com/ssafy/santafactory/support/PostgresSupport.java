package com.ssafy.santafactory.support;

import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * 컨텍스트를 띄우는 테스트의 공통 부모 — 운영과 같은 Postgres 를 쓴다.
 *
 * <p>스키마는 <b>Flyway 가 운영과 똑같은 마이그레이션으로</b> 만든다. 여기에
 * {@code ddl-auto=validate}(test/resources/application.yml)로 붙기 때문에
 * <b>엔티티와 마이그레이션이 어긋나면 컨텍스트 로딩이 실패한다.</b>
 * H2 는 엔티티에서 스키마를 만들어버려서 이 검증이 구조적으로 불가능했다.
 *
 * <p>데모 시드({@code db/seed})는 테스트에서 제외된다 — 이유는 {@code R__seed_demo.sql} 주석 참고.
 *
 * <p>Redis 도 함께 띄운다(S15P21A106-186). refresh 토큰 회전·재사용 감지는 저장소 동작이라
 * 목으로는 검증되지 않고, Postgres 와 수명이 같아 한곳에 모아 두는 게 단순하다.
 *
 * <p>DB 를 잡는 순서:
 * <ol>
 *   <li>{@code DB_URL} 환경변수가 있으면 그 DB 를 쓴다 — docker-compose 로 이미 띄운 경우.
 *       <b>Flyway 가 그 DB 에 실제로 마이그레이션을 적용한다</b>(시드는 제외).</li>
 *   <li>없으면 Testcontainers 로 빈 Postgres 를 띄운다 (Docker 필요).</li>
 * </ol>
 */
public abstract class PostgresSupport {

    private static final String JDBC_URL;
    private static final String USERNAME;
    private static final String PASSWORD;
    private static final String REDIS_HOST;
    private static final int REDIS_PORT;

    static {
        String envUrl = System.getenv("DB_URL");
        if (envUrl != null && !envUrl.isBlank()) {
            JDBC_URL = envUrl;
            USERNAME = envOrDefault("DB_USERNAME", "postgres");
            PASSWORD = envOrDefault("DB_PASSWORD", "postgres");
        } else {
            // 초기 스크립트를 주지 않는다 — 스키마는 Flyway 가 컨텍스트 로딩 때 만든다.
            PostgreSQLContainer<?> container = new PostgreSQLContainer<>("postgres:16-alpine");
            container.start();   // JVM 종료 시 Ryuk 이 정리한다
            JDBC_URL = container.getJdbcUrl();
            USERNAME = container.getUsername();
            PASSWORD = container.getPassword();
        }

        // 비밀번호 없이 띄운다 — 테스트 컨테이너는 외부에 노출되지 않는다
        GenericContainer<?> redis = new GenericContainer<>("redis:7-alpine").withExposedPorts(6379);
        redis.start();
        REDIS_HOST = redis.getHost();
        REDIS_PORT = redis.getMappedPort(6379);
    }

    private static String envOrDefault(String name, String fallback) {
        String value = System.getenv(name);
        return (value == null || value.isBlank()) ? fallback : value;
    }

    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", () -> JDBC_URL);
        registry.add("spring.datasource.username", () -> USERNAME);
        registry.add("spring.datasource.password", () -> PASSWORD);
        registry.add("spring.data.redis.host", () -> REDIS_HOST);
        registry.add("spring.data.redis.port", () -> REDIS_PORT);
        registry.add("spring.data.redis.password", () -> "");
    }
}
