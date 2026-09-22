package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.simulation.RunReplay;
import org.springframework.data.jpa.repository.JpaRepository;

/** run 리플레이 궤적. 키가 run(scenario) id 그대로라 {@code findById(run.getId())} 로 읽는다. */
public interface RunReplayRepository extends JpaRepository<RunReplay, Long> {
}
