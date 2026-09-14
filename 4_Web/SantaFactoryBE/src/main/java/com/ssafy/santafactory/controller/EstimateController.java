package com.ssafy.santafactory.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.ssafy.santafactory.dto.estimate.EstimateCreateRequest;
import com.ssafy.santafactory.dto.estimate.EstimateCreateResponse;
import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.estimate.EstimateSummaryResponse;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.estimate.EstimateEventStream;
import com.ssafy.santafactory.service.estimate.EstimateService;
import com.ssafy.santafactory.service.estimate.VerifyEventStream;
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
import org.springframework.security.core.annotation.AuthenticationPrincipal;
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
    private final VerifyEventStream verifyEventStream;

    @Operation(summary = "견적 요청 생성",
            description = "창고 운영조건 + 목표 + 예산으로 대수별 run 을 만들어 시뮬 엔진에 전부 발행한다. "
                    + "목표·예산을 비워 보내면 창고 기본값을 쓴다.")
    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ApiResponse<EstimateCreateResponse> create(@Valid @RequestBody EstimateCreateRequest request,
                                                      @AuthenticationPrincipal AuthenticatedMember me) {
        return ApiResponse.onSuccess(estimateService.create(request, me));
    }

    @Operation(summary = "견적 목록", description = "최근순")
    @GetMapping
    public ApiResponse<Page<EstimateSummaryResponse>> list(
            @PageableDefault(size = 20, sort = "createdAt", direction = Sort.Direction.DESC) Pageable pageable,
            @AuthenticationPrincipal AuthenticatedMember me) {
        return ApiResponse.onSuccess(estimateService.list(pageable, me));
    }

    @Operation(summary = "견적 상세",
            description = "견적 상태 + 대수별 결과표(대수·처리율·가동률·비용) + 권장 대수·효율 감소 지점. "
                    + "같은 URL 을 Accept: text/event-stream 으로 열면 SSE 스트림이 된다.")
    @GetMapping(value = "/{estimateId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ApiResponse<EstimateDetailResponse> detail(@PathVariable Long estimateId,
                                                      @AuthenticationPrincipal AuthenticatedMember me) {
        return ApiResponse.onSuccess(estimateService.detail(estimateId, me));
    }

    @Operation(summary = "대수별 주행 리플레이",
            description = "그 대수 run 의 앞 구간 궤적과 맵. 견적을 돌릴 때 함께 만들어 둔 것이라 즉시 응답한다. "
                    + "아직 결과가 없거나 그 run 이 실패했으면 404 — 프론트는 두 경우를 같게 다루면 된다.")
    @GetMapping("/{estimateId}/runs/{amrCount}/replay")
    public ApiResponse<JsonNode> replay(@PathVariable Long estimateId,
                                        @PathVariable int amrCount,
                                        @AuthenticationPrincipal AuthenticatedMember me) {
        return ApiResponse.onSuccess(estimateService.replay(estimateId, amrCount, me));
    }

    /**
     * 진행 스트림. Accept: text/event-stream 일 때만 이쪽으로 온다 — Accept 가 없거나 {@code *}{@code /*}
     * 이면 Spring 이 미디어 타입 이름순으로 application/json 을 먼저 고르므로 위 JSON 핸들러가 잡는다.
     * X-Accel-Buffering 은 앞단 nginx 가 이 응답만 버퍼링하지 않게 하는 헤더다.
     */
    @Operation(summary = "견적 진행 스트림 (SSE)",
            description = "snapshot(현재 상태) → run(결과 도착마다) → estimate.done 순으로 보내고 닫는다.")
    @GetMapping(value = "/{estimateId}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<SseEmitter> stream(@PathVariable Long estimateId,
                                            @AuthenticationPrincipal AuthenticatedMember me) {
        estimateService.checkAccess(estimateId, me);
        return ResponseEntity.ok()
                .header("X-Accel-Buffering", "no")
                .body(eventStream.subscribe(estimateId));
    }

    @Operation(summary = "물리 검증 결과 스트림 (SSE)",
            description = "영상이 이미 있으면 snapshot 으로 바로 보내고 닫는다. 없으면 결과가 올 때까지 "
                    + "열어두고 verify.done 을 보낸 뒤 닫는다. 견적 진행 스트림과는 별도 채널이다.")
    @GetMapping(value = "/{estimateId}/verify", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<SseEmitter> verifyStream(@PathVariable Long estimateId,
                                                  @AuthenticationPrincipal AuthenticatedMember me) {
        estimateService.checkAccess(estimateId, me);
        return ResponseEntity.ok()
                .header("X-Accel-Buffering", "no")
                .body(verifyEventStream.subscribe(estimateId));
    }

    @Operation(summary = "물리 검증 요청",
            description = "권장 대수로 sim.verify.request 를 발행한다. 권장 대수가 없는 견적(사유만 있는 "
                    + "판정)은 검증할 대상이 없어 거부한다.")
    @PostMapping("/{estimateId}/verify")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public ApiResponse<Void> requestVerification(@PathVariable Long estimateId,
                                                 @AuthenticationPrincipal AuthenticatedMember me) {
        estimateService.requestVerification(estimateId, me);
        return ApiResponse.onSuccess();
    }

    @Operation(summary = "견적 취소",
            description = "이미 큐에 들어간 run 은 결과가 와도 판정에 반영되지 않는다")
    @DeleteMapping("/{estimateId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public ApiResponse<Void> cancel(@PathVariable Long estimateId,
                                    @AuthenticationPrincipal AuthenticatedMember me) {
        estimateService.cancel(estimateId, me);
        return ApiResponse.onSuccess();
    }
}
