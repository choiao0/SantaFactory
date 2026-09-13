package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.entity.estimate.EstimateStatus;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateFinished;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunUpdated;
import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 견적 진행 상황 SSE.
 *
 * <p>브라우저가 {@code GET /api/estimates/{id}} 를 {@code Accept: text/event-stream} 으로 열면
 * 현재 상태를 {@code snapshot} 으로 한 번 보내고, 이후 run 결과가 도착할 때마다 {@code run} 을,
 * 판정이 끝나면 {@code estimate.done} 을 보낸 뒤 닫는다. 결과 큐 수신이 곧 push 이므로 폴링이 없다.
 *
 * <p>이벤트는 DB 트랜잭션이 커밋된 뒤에만 보낸다 — 브라우저가 이벤트를 받고 새로고침했을 때
 * 스냅샷이 이벤트보다 뒤처지는 일이 없게 하기 위함이다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class EstimateEventStream {

    public static final String EVENT_SNAPSHOT = "snapshot";
    public static final String EVENT_RUN = "run";
    public static final String EVENT_DONE = "estimate.done";

    /** run 타임아웃(30분)보다 길게 잡아, 마지막 run 이 TIMEOUT 으로 정리될 때까지는 연결이 살아 있게 한다. */
    private static final long EMITTER_TIMEOUT_MS = Duration.ofMinutes(35).toMillis();

    private final EstimateService estimateService;
    private final Map<Long, List<SseEmitter>> emitters = new ConcurrentHashMap<>();

    /**
     * 구독을 열고 현재 상태를 첫 이벤트로 보낸다. 이미 끝난 견적이면 등록하지 않고 done 까지 보낸 뒤
     * 바로 닫는다 — 응답이 열리기 전에 보낸 이벤트는 SseEmitter 가 버퍼링해 두었다가 함께 내보낸다.
     */
    public SseEmitter subscribe(Long estimateId) {
        EstimateDetailResponse snapshot = estimateService.snapshot(estimateId);
        SseEmitter emitter = new SseEmitter(EMITTER_TIMEOUT_MS);
        if (snapshot.status() == EstimateStatus.RUNNING) {
            register(estimateId, emitter);
        }
        send(estimateId, emitter, EVENT_SNAPSHOT, snapshot);
        if (snapshot.status() != EstimateStatus.RUNNING) {
            send(estimateId, emitter, EVENT_DONE, new EstimateFinished(
                    estimateId, snapshot.status(), snapshot.recommendedCount(),
                    snapshot.kneeCount(), snapshot.reasonCode()));
            emitter.complete();
        }
        return emitter;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onRunUpdated(RunUpdated event) {
        broadcast(event.estimateId(), EVENT_RUN, event.run());
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onEstimateFinished(EstimateFinished event) {
        broadcast(event.estimateId(), EVENT_DONE, event);
        List<SseEmitter> targets = emitters.remove(event.estimateId());
        if (targets != null) {
            targets.forEach(SseEmitter::complete);
        }
    }

    /** 프록시(nginx)의 read timeout 에 끊기지 않게 주기적으로 주석 프레임을 보낸다. */
    @Scheduled(fixedDelayString = "${estimate.sse-heartbeat-seconds:15}", timeUnit = java.util.concurrent.TimeUnit.SECONDS)
    public void heartbeat() {
        emitters.forEach((estimateId, targets) -> targets.forEach(emitter -> {
            try {
                emitter.send(SseEmitter.event().comment("ping"));
            } catch (IOException | IllegalStateException e) {
                drop(estimateId, emitter);
            }
        }));
    }

    int subscriberCount(Long estimateId) {
        return emitters.getOrDefault(estimateId, List.of()).size();
    }

    private void register(Long estimateId, SseEmitter emitter) {
        emitters.computeIfAbsent(estimateId, id -> new CopyOnWriteArrayList<>()).add(emitter);
        emitter.onCompletion(() -> drop(estimateId, emitter));
        emitter.onTimeout(() -> drop(estimateId, emitter));
        emitter.onError(e -> drop(estimateId, emitter));
    }

    private void broadcast(Long estimateId, String name, Object payload) {
        List<SseEmitter> targets = emitters.get(estimateId);
        if (targets == null) {
            return;
        }
        targets.forEach(emitter -> send(estimateId, emitter, name, payload));
    }

    private void send(Long estimateId, SseEmitter emitter, String name, Object payload) {
        try {
            emitter.send(SseEmitter.event().name(name).data(payload));
        } catch (IOException | IllegalStateException e) {
            log.debug("SSE 전송 실패로 구독 해제: estimateId={}, event={}", estimateId, name);
            drop(estimateId, emitter);
        }
    }

    private void drop(Long estimateId, SseEmitter emitter) {
        emitters.computeIfPresent(estimateId, (id, targets) -> {
            targets.remove(emitter);
            return targets.isEmpty() ? null : targets;
        });
    }
}
