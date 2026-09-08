package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.estimate.RunStatus;
import com.ssafy.santafactory.entity.simulation.SimScenario;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface SimScenarioRepository extends JpaRepository<SimScenario, Long> {

    /** 결과 메시지의 run_id 로 run 을 찾는다. 없으면 유령 결과이므로 무시한다. */
    Optional<SimScenario> findByRunId(String runId);

    /** 견적의 대수별 결과 — 판정과 조회 표에 쓴다. */
    List<SimScenario> findByEstimateIdOrderByAmrCountAsc(Long estimateId);

    /** 아직 결과를 기다리는 run 이 남았는지 — 전 대수 완료 판정. */
    boolean existsByEstimateIdAndStatusIn(Long estimateId, Collection<RunStatus> statuses);

    /** 발행된 지 오래됐는데 결과가 없는 run — TIMEOUT 처리 대상. */
    List<SimScenario> findByStatusInAndPublishedAtBefore(Collection<RunStatus> statuses, LocalDateTime threshold);
}
