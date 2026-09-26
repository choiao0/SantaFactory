package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse.VerificationRun;
import com.ssafy.santafactory.service.estimate.EstimateEvents.VerificationUpdated;
import com.ssafy.santafactory.service.estimate.EstimateEvents.VerificationsFinished;
import com.ssafy.santafactory.service.estimate.EstimateEvents.VerificationsSnapshot;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 대수별 물리 검증(Isaac) 결과 SSE (S15P21A106-244) — 견적 진행 스트림({@link EstimateEventStream})과
 * 완전히 분리된 채널이다.
 *
 * <p>검증은 견적이 이미 DONE 으로 끝난 뒤에 도는데, 그 스트림은 "RUNNING 일 때만 연결을 유지"하고
 * 그 외엔 바로 닫아버려서 검증 결과를 얹을 자리가 없다. 그래서 완전히 새 구독 채널을 둔다.
 *
 * <p>후보 여러 대수를 동시에 검증하므로(-244) 첫 결과가 왔다고 연결을 끊지 않는다 — 나머지 후보가
 * 아직 진행 중일 수 있어서다. {@code verify.run} 을 회차마다, 전부 끝나면(PENDING/RUNNING 없음)
 * {@code verify.done} 을 보낸 뒤 닫는다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class VerifyEventStream {

    public static final String EVENT_SNAPSHOT = "snapshot";
    public static final String EVENT_RUN = "verify.run";
    public static final String EVENT_DONE = "verify.done";

    private static final long EMITTER_TIMEOUT_MS = Duration.ofMinutes(35).toMillis();

    private final EstimateService estimateService;
    private final Map<Long, List<SseEmitter>> emitters = new ConcurrentHashMap<>();

    /**
     * 구독을 열고 현재 대수별 상태를 스냅샷으로 보낸다. 한 번도 검증하지 않았거나(빈 리스트) 진행 중인
     * 회차가 있으면 연결을 열어 둔다. 전부 끝난 상태(재구독·새로고침)면 스냅샷만 보내고 바로 닫는다.
     */
    public SseEmitter subscribe(Long estimateId) {
        SseEmitter emitter = new SseEmitter(EMITTER_TIMEOUT_MS);
        register(estimateId, emitter);
        VerificationsSnapshot snapshot = estimateService.verifySnapshot(estimateId);
        send(estimateId, emitter, EVENT_SNAPSHOT, snapshot);
        if (allFinished(snapshot)) {
            drop(estimateId, emitter);
            emitter.complete();
        }
        return emitter;
    }

    /** 검증한 적이 없으면(빈 리스트) 아직 열어 둘 이유가 있다 — 사람이 버튼을 누르길 기다리는 중이다. */
    private boolean allFinished(VerificationsSnapshot snapshot) {
        List<VerificationRun> verifications = snapshot.verifications();
        return !verifications.isEmpty() && verifications.stream().noneMatch(this::isPending);
    }

    private boolean isPending(VerificationRun run) {
        return "PENDING".equals(run.status()) || "RUNNING".equals(run.status());
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onVerificationUpdated(VerificationUpdated event) {
        broadcast(event.estimateId(), EVENT_RUN, event);
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onVerificationsFinished(VerificationsFinished event) {
        VerificationsSnapshot snapshot = estimateService.verifySnapshot(event.estimateId());
        broadcast(event.estimateId(), EVENT_DONE, snapshot);
        List<SseEmitter> targets = emitters.remove(event.estimateId());
        if (targets != null) {
            targets.forEach(SseEmitter::complete);
        }
    }

    /** 프록시(nginx)의 read timeout 에 끊기지 않게 주기적으로 주석 프레임을 보낸다. */
    @Scheduled(fixedDelayString = "${estimate.sse-heartbeat-seconds:15}", timeUnit = TimeUnit.SECONDS)
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

    /** 종료 시 열린 구독을 전부 닫는다 — 이유는 {@link EstimateEventStream#closeAll()} 과 같다. */
    @PreDestroy
    public void closeAll() {
        emitters.values().forEach(targets -> targets.forEach(SseEmitter::complete));
        emitters.clear();
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
