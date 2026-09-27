package com.ssafy.santafactory.controller;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.ssafy.santafactory.support.PostgresSupport;
import com.ssafy.santafactory.support.RedisSupport;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

/**
 * k3s 가 토큰 없이 부르는 준비·생존 확인 경로 (S15P21A106-258).
 *
 * <p>readiness·liveness 그룹은 앱 자신의 상태만 보므로 RabbitMQ 가 없는 테스트 환경에서도 200 이어야 한다.
 * 401 이 나면 SecurityConfig 의 공개 목록에서 빠진 것이고, 503 이면 그룹에 외부 의존 항목이 섞인 것이다.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(RedisSupport.class)
class HealthProbeIT extends PostgresSupport {

    @Autowired
    MockMvc mvc;

    @Test
    void readiness_and_liveness_are_reachable_without_a_token() throws Exception {
        mvc.perform(get("/actuator/health/readiness")).andExpect(status().isOk());
        mvc.perform(get("/actuator/health/liveness")).andExpect(status().isOk());
    }

    @Test
    void other_actuator_endpoints_stay_closed() throws Exception {
        mvc.perform(get("/actuator/env")).andExpect(status().isUnauthorized());
    }
}
