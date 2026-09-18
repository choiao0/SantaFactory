package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.service.SimulationService;
import com.ssafy.santafactory.service.estimate.EstimateEvents.RunsQueued;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

import java.util.List;

/**
 * 견적의 run 행이 커밋된 뒤에 요청 큐로 발행한다.
 *
 * <p>워커는 run 을 집는 즉시 {@code status: running} 을 결과 큐로 돌려보내는데, 발행이 커밋보다 앞서면
 * 그 응답이 아직 보이지 않는 run 행을 찾다 버려진다. 커밋 뒤에 발행하면 워커가 아무리 빨라도 행이 먼저다.
 * 발행이 중간에 실패하면 그 run 부터 나머지를 FAILED 로 닫는다 — 앞서 나간 run 은 정상 진행한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SimRequestDispatcher {

    private final SimulationService simulationService;
    private final EstimateService estimateService;

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onRunsQueued(RunsQueued event) {
        List<Integer> amrCounts = event.amrCounts();
        for (int i = 0; i < amrCounts.size(); i++) {
            try {
                simulationService.publishRun(event.request(), amrCounts.get(i));
            } catch (GlobalException e) {
                List<Integer> unpublished = amrCounts.subList(i, amrCounts.size());
                log.error("요청 발행 중단: estimateId={}, 미발행 대수={}", event.estimateId(), unpublished, e);
                estimateService.failUnpublished(event.estimateId(), unpublished, e.getErrorCode().getMessage());
                return;
            }
        }
        log.info("시뮬레이션 요청 발행: estimateId={}, 대수={}", event.estimateId(), amrCounts);
    }
}
