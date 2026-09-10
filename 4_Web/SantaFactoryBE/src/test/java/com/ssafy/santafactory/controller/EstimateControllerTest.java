package com.ssafy.santafactory.controller;

import static org.hamcrest.Matchers.startsWith;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.service.estimate.EstimateEventStream;
import com.ssafy.santafactory.service.estimate.EstimateService;
import com.ssafy.santafactory.service.estimate.VerifyEventStream;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** 같은 URL 이 Accept 헤더로 JSON 스냅샷과 SSE 를 가른다. */
@WebMvcTest(EstimateController.class)
class EstimateControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    EstimateService estimateService;

    @MockBean
    EstimateEventStream eventStream;

    @MockBean
    VerifyEventStream verifyEventStream;

    private static final EstimateDetailResponse DETAIL = new EstimateDetailResponse(
            77L, EstimateStatus.RUNNING, "iw.hub", 95.0, 80.0, 300_000_000L,
            null, null, null, LocalDateTime.of(2026, 9, 8, 10, 0), null, null, List.of());

    @Test
    void json_by_default() throws Exception {
        when(estimateService.detail(77L)).thenReturn(DETAIL);

        mvc.perform(get("/api/estimates/77"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", startsWith(MediaType.APPLICATION_JSON_VALUE)))
                .andExpect(jsonPath("$.isSuccess").value(true))
                .andExpect(jsonPath("$.result.estimate_id").value(77))
                .andExpect(jsonPath("$.result.status").value("RUNNING"));

        verify(eventStream, never()).subscribe(anyLong());
    }

    @Test
    void wildcard_accept_is_still_json() throws Exception {
        when(estimateService.detail(77L)).thenReturn(DETAIL);

        mvc.perform(get("/api/estimates/77").accept(MediaType.ALL))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", startsWith(MediaType.APPLICATION_JSON_VALUE)));

        verify(eventStream, never()).subscribe(anyLong());
    }

    @Test
    void event_stream_when_the_client_asks_for_it() throws Exception {
        // 헤더는 첫 이벤트를 flush 할 때 함께 써지므로, 스냅샷을 이미 보낸 emitter 를 흉내낸다
        SseEmitter emitter = new SseEmitter();
        emitter.send(SseEmitter.event().name("snapshot").data("{}"));
        when(eventStream.subscribe(77L)).thenReturn(emitter);

        mvc.perform(get("/api/estimates/77").accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isOk())
                .andExpect(request().asyncStarted())
                .andExpect(header().string("Content-Type", startsWith(MediaType.TEXT_EVENT_STREAM_VALUE)))
                .andExpect(header().string("X-Accel-Buffering", "no"));

        verify(eventStream).subscribe(77L);
        verify(estimateService, never()).detail(anyLong());
    }

    /** SSE 라우트에서도 예외가 JSON 협상 실패로 500 이 되지 않고 깔끔한 상태 코드로 나가야 한다. */
    @Test
    void unknown_estimate_gets_a_clean_404_even_over_the_verify_sse_route() throws Exception {
        when(verifyEventStream.subscribe(999L)).thenThrow(new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));

        mvc.perform(get("/api/estimates/999/verify").accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value(ErrorCode.ESTIMATE_NOT_FOUND.getCode()));
    }
}
