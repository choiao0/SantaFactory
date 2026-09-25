package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.estimate.EstimateVerification;
import com.ssafy.santafactory.entity.estimate.VerifyRunStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface EstimateVerificationRepository extends JpaRepository<EstimateVerification, Long> {

    /** 결과 메시지의 run_id 로 회차를 찾는다 — 새 형식({@code verify_<id>_n<K>_<attempt>})만 여기 있다. */
    Optional<EstimateVerification> findByRunId(String runId);

    /** 대수별 최신 시도가 먼저 오도록 — 상세·SSE 스냅샷에서 대수당 첫 값만 골라 쓴다. */
    List<EstimateVerification> findByEstimateIdOrderByRobotCountAscAttemptDesc(Long estimateId);

    /** 같은 (견적, 대수)의 마지막 시도 번호 — 다음 attempt 계산에 쓴다. */
    Optional<EstimateVerification> findFirstByEstimateIdAndRobotCountOrderByAttemptDesc(Long estimateId, Integer robotCount);

    /** 아직 끝나지 않은 회차가 있는가 — 중복 요청 가드·verify.done 판단에 쓴다. */
    boolean existsByEstimateIdAndStatusIn(Long estimateId, Collection<VerifyRunStatus> statuses);
}
