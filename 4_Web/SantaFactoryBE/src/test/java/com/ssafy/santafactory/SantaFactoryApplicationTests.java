package com.ssafy.santafactory;

import com.ssafy.santafactory.support.PostgresSupport;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class SantaFactoryApplicationTests extends PostgresSupport {

    /** 빈 배선과 함께 엔티티 ↔ db/santafactory.sql 일치까지 검사한다 (ddl-auto=validate). */
    @Test
    void contextLoads() {
    }
}
