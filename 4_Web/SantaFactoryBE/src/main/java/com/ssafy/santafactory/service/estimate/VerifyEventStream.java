package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.service.estimate.EstimateEvents.EstimateVerified;
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
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 물리 검증(Isaac) 결과 SSE — 견적 진행 스트림({@link EstimateEventStream})과 완전히 분리된 채널이다.
 *
 * <p>검증은 견적이 이미 DONE 으로 끝난 뒤에 도는데, 그 스트림은 "RUNNING 일 때만 연결을 유지"하고
 * 그 외엔 바로 닫아버려서 검증 결과를 얹을 자리가 없다. 그래서 완전히 새 구독 채널을 둔다.
 *
 * <p>이미 영상이 있으면(재구독·새로고침) snapshot 으로 바로 보내고 닫는다. 없으면 연결을 열어두고
 * 결과가 오면 {@code verify.done} 을 보낸 뒤 닫는다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class VerifyEventStream {

    public static final String EVENT_SNAPSHOT = "snapshot";
    public static final String EVENT_DONE = "verify.done";

    private static final long EMITTER_TIMEOUT_MS = Duration.ofMinutes(35).toMillis();

    private final EstimateRepository estimateRepository;
    private final VerifyVideoPresigner videoPresigner;
    private final Map<Long, List<SseEmitter>> emitters = new ConcurrentHashMap<>();

    @Transactional(readOnly = true)
    public SseEmitter subscribe(Long estimateId) {
        Estimate estimate = estimateRepository.findById(estimateId)
                .orElseThrow(() -> new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND));
        SseEmitter emitter = new SseEmitter(EMITTER_TIMEOUT_MS);
        String video = estimate.getVerifyVideoUrl();
        if (video == null) {
            register(estimateId, emitter);
            send(estimateId, emitter, EVENT_SNAPSHOT, new EstimateVerified(estimateId, "PENDING", null, null));
        } else {
            send(estimateId, emitter, EVENT_DONE,
                    new EstimateVerified(estimateId, "done", videoPresigner.sign(video), null));
            emitter.complete();
        }
        return emitter;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onEstimateVerified(EstimateVerified event) {
        List<SseEmitter> targets = emitters.remove(event.estimateId());
        if (targets == null) {
            return;
        }
        targets.forEach(emitter -> send(event.estimateId(), emitter, EVENT_DONE, event));
        targets.forEach(SseEmitter::complete);
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
