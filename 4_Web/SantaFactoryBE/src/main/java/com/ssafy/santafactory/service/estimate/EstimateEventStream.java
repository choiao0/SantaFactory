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
     * 구독을 열고 현재 상태를 첫 이벤트로 보낸다. 이미 끝난 견적이면 done 까지 보낸 뒤 바로 닫는다 —
     * 응답이 열리기 전에 보낸 이벤트는 SseEmitter 가 버퍼링해 두었다가 함께 내보낸다.
     *
     * <p><b>등록이 스냅샷보다 먼저다.</b> 순서를 뒤집으면 그 사이에 커밋된 run 이벤트가 양쪽에서 빠진다 —
     * 스냅샷은 이미 읽혔고 {@link #broadcast} 는 아직 보낼 대상이 없다. 그 run 은 화면에서 "대기" 로
     * 굳었다가 결과가 와서야 "완료" 로 튄다 (S15P21A106-263). 견적을 요청한 직후 워커들이 일제히
     * running 을 보내는 시점과 구독 시점이 겹치므로 실제로 걸린다.
     *
     * <p>먼저 등록하면 그 사이 이벤트가 스냅샷보다 앞서 나갈 수 있는데, 스냅샷을 나중에 읽으므로
     * 그 변경이 스냅샷에도 들어 있다 — 화면은 둘 중 무엇을 먼저 받아도 같은 상태가 된다.
     */
    public SseEmitter subscribe(Long estimateId) {
        SseEmitter emitter = new SseEmitter(EMITTER_TIMEOUT_MS);
        register(estimateId, emitter);
        EstimateDetailResponse snapshot = estimateService.snapshot(estimateId);
        send(estimateId, emitter, EVENT_SNAPSHOT, snapshot);
        if (snapshot.status() != EstimateStatus.RUNNING) {
            send(estimateId, emitter, EVENT_DONE, new EstimateFinished(
                    estimateId, snapshot.status(), snapshot.recommendedCount(),
                    snapshot.minimalCount(), snapshot.kneeCount(), snapshot.reasonCode()));
            // 등록을 먼저 했으니 여기서 직접 뗀다 — onCompletion 은 응답이 붙은 뒤에야 도는 콜백이라
            // 그것만 믿으면 이미 끝난 견적의 emitter 가 목록에 남는다
            drop(estimateId, emitter);
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
