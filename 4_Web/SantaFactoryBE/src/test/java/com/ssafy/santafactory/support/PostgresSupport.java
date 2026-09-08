package com.ssafy.santafactory.support;

import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * 컨텍스트를 띄우는 테스트의 공통 부모 — 운영과 같은 Postgres 를 쓴다.
 *
 * <p>{@code ddl-auto=validate}(test/resources/application.yml)로 붙기 때문에
 * <b>엔티티와 손으로 쓴 {@code db/santafactory.sql} 이 어긋나면 컨텍스트 로딩이 실패한다.</b>
 * H2 는 엔티티에서 스키마를 만들어버려서 이 검증이 구조적으로 불가능했다.
 *
 * <p>DB 를 잡는 순서:
 * <ol>
 *   <li>{@code DB_URL} 환경변수가 있으면 그 DB 를 쓴다 — docker-compose 로 이미 띄운 경우.
 *       스키마는 {@code db/santafactory.sql} 이 적용돼 있어야 한다.</li>
 *   <li>없으면 Testcontainers 로 직접 띄우고 초기 스크립트로 스키마를 만든다 (Docker 필요).</li>
 * </ol>
 */
public abstract class PostgresSupport {

    private static final String SCHEMA_SCRIPT = "db/santafactory.sql";

    private static final String JDBC_URL;
    private static final String USERNAME;
    private static final String PASSWORD;

    static {
        String envUrl = System.getenv("DB_URL");
        if (envUrl != null && !envUrl.isBlank()) {
            JDBC_URL = envUrl;
            USERNAME = envOrDefault("DB_USERNAME", "postgres");
            PASSWORD = envOrDefault("DB_PASSWORD", "postgres");
        } else {
            PostgreSQLContainer<?> container = new PostgreSQLContainer<>("postgres:16-alpine")
                    .withInitScript(SCHEMA_SCRIPT);
            container.start();   // JVM 종료 시 Ryuk 이 정리한다
            JDBC_URL = container.getJdbcUrl();
            USERNAME = container.getUsername();
            PASSWORD = container.getPassword();
        }
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
    }
}
