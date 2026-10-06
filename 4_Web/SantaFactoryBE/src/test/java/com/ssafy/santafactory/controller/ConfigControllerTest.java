package com.ssafy.santafactory.controller;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.ssafy.santafactory.global.auth.TrialMode;
import com.ssafy.santafactory.support.WebMvcSecuritySupport;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

/** 체험 모드 안내 배너는 로그인·가입 화면에도 떠야 해서 토큰 없이 읽힌다 (S15P21A106-283). */
@WebMvcTest(ConfigController.class)
@Import(WebMvcSecuritySupport.class)
class ConfigControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    TrialMode trialMode;

    @Test
    void tells_anyone_without_a_token_that_the_trial_mode_is_on() throws Exception {
        when(trialMode.enabled()).thenReturn(true);

        mvc.perform(get("/api/config"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.result.trial_mode").value(true));
    }

    @Test
    void reports_off_as_false() throws Exception {
        when(trialMode.enabled()).thenReturn(false);

        mvc.perform(get("/api/config"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.result.trial_mode").value(false));
    }
}
