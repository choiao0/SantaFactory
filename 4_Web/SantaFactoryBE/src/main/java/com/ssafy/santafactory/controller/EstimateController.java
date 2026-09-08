package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateSummaryResponse;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.estimate.EstimateEventStream;
import com.ssafy.santafactory.service.estimate.EstimateService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Tag(name = "견적", description = "AMR 대수별 시뮬을 돌려 권장 대수를 뽑는다")
@RestController
@RequestMapping("/api/estimates")
@RequiredArgsConstructor
public class EstimateController {

    private final EstimateService estimateService;
    private final EstimateEventStream eventStream;

    @Operation(summary = "견적 요청 생성",
            description = "창고 운영조건 + 목표 + 예산으로 대수별 run 을 만들어 시뮬 엔진에 전부 발행한다. "
                    + "목표·예산을 비워 보내면 창고 기본값을 쓴다.")
    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ApiResponse<EstimateCreateResponse> create(@Valid @RequestBody EstimateCreateRequest request) {
        return ApiResponse.onSuccess(estimateService.create(request));
    }

    @Operation(summary = "견적 목록", description = "최근순")
    @GetMapping
    public ApiResponse<Page<EstimateSummaryResponse>> list(
            @PageableDefault(size = 20, sort = "createdAt", direction = Sort.Direction.DESC) Pageable pageable) {
        return ApiResponse.onSuccess(estimateService.list(pageable));
    }

    @Operation(summary = "견적 상세",
            description = "견적 상태 + 대수별 결과표(대수·처리율·가동률·비용) + 권장 대수·효율 감소 지점. "
                    + "같은 URL 을 Accept: text/event-stream 으로 열면 SSE 스트림이 된다.")
    @GetMapping(value = "/{estimateId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<EstimateDetailResponse> detail(@PathVariable Long estimateId) {
        return ApiResponse.onSuccess(estimateService.detail(estimateId));
    }

    /**
     * 진행 스트림. Accept: text/event-stream 일 때만 이쪽으로 온다 — Accept 가 없거나 {@code *}{@code /*}
     * 이면 Spring 이 미디어 타입 이름순으로 application/json 을 먼저 고르므로 위 JSON 핸들러가 잡는다.
     * X-Accel-Buffering 은 앞단 nginx 가 이 응답만 버퍼링하지 않게 하는 헤더다.
     */
    @Operation(summary = "견적 진행 스트림 (SSE)",
            description = "snapshot(현재 상태) → run(결과 도착마다) → estimate.done 순으로 보내고 닫는다.")
    @GetMapping(value = "/{estimateId}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<SseEmitter> stream(@PathVariable Long estimateId) {
        return ResponseEntity.ok()
                .header("X-Accel-Buffering", "no")
                .body(eventStream.subscribe(estimateId));
    }

    @Operation(summary = "견적 취소",
            description = "이미 큐에 들어간 run 은 결과가 와도 판정에 반영되지 않는다")
    @DeleteMapping("/{estimateId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public ApiResponse<Void> cancel(@PathVariable Long estimateId) {
        estimateService.cancel(estimateId);
        return ApiResponse.onSuccess();
    }
}
